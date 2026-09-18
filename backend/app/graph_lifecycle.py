from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from app.database import UPLOAD_DIR, connect
from app.models import (
    DocumentImpact,
    ExtractionJob,
    GraphQuality,
    GraphVersion,
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    LearningPathResult,
    QAResult,
    User,
)
from app.platform import _audit, _graph_dict, _insert_chunks
from app.services import deepseek
from app.services.retrieval import fts_query, search_tokens


def document_saved(document_id: str, course_id: str, content: str, user: User) -> None:
    with connect() as connection:
        active = connection.execute("SELECT active_version_id FROM courses WHERE id = ?", (course_id,)).fetchone()
        connection.execute(
            "UPDATE documents SET baseline_version_id = ? WHERE id = ?",
            ((active["active_version_id"] if active else ""), document_id),
        )
        _insert_chunks(connection, document_id, course_id, content)
        _audit(connection, user, "document.upload", "document", document_id, {"course_id": course_id})


def create_extraction_job(course_id: str, user: User) -> ExtractionJob:
    _assert_course_manage(course_id, user)
    with connect() as connection:
        documents = connection.execute(
            "SELECT id FROM documents WHERE course_id = ? AND status = 'active' ORDER BY created_at DESC", (course_id,)
        ).fetchall()
        if not documents:
            raise ValueError("请先上传至少一份课程资料")
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        mode = deepseek.extraction_mode()
        connection.execute(
            """
            INSERT INTO extraction_jobs(
              id, course_id, requested_by, document_ids_json, status, progress, mode, message
            ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
            """,
            (
                job_id, course_id, user.id, json.dumps([row["id"] for row in documents]), mode,
                "等待知识抽取" if mode == "deepseek" else "本地规则模式：等待知识抽取",
            ),
        )
        _audit(connection, user, "extraction.create", "course", course_id, {"job_id": job_id, "mode": mode})
    return get_extraction_job(job_id, user)


def process_extraction_job(job_id: str) -> None:
    with connect() as connection:
        job = connection.execute("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job or job["status"] not in ("queued", "failed"):
            return
        connection.execute(
            "UPDATE extraction_jobs SET status = 'parsing', progress = 15, message = '正在读取课程资料', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id,),
        )
    try:
        with connect() as connection:
            course = connection.execute("SELECT name FROM courses WHERE id = ?", (job["course_id"],)).fetchone()
            document_ids = json.loads(job["document_ids_json"])
            placeholders = ",".join("?" for _ in document_ids)
            documents = [dict(row) for row in connection.execute(
                f"SELECT id, filename, content FROM documents WHERE id IN ({placeholders}) AND status = 'active' ORDER BY created_at DESC",
                document_ids,
            ).fetchall()]
            connection.execute(
                "UPDATE extraction_jobs SET status = 'extracting', progress = 45, message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("正在调用 DeepSeek 进行结构化抽取" if job["mode"] == "deepseek" else "正在运行本地规则抽取", job_id),
            )
        extraction_warnings: list[str] = []
        extracted_graph = deepseek.extract_graph(course["name"], documents, warnings=extraction_warnings)
        with connect() as connection:
            active_graph = KnowledgeGraph(**_graph_dict(connection, job["course_id"]))
            graph, added_nodes, added_edges = _merge_graphs(active_graph, extracted_graph)
            quality_warning = _extraction_quality_warning(extracted_graph) if job["mode"] == "deepseek" else ""
            quality_warning = "；".join(filter(None, [*extraction_warnings, quality_warning]))
            quality_suffix = f"；质量提醒：{quality_warning}" if quality_warning else ""
            connection.execute(
                "UPDATE extraction_jobs SET status = 'merging', progress = 78, message = '正在融合知识点与关系', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
            version_id = _create_version(
                connection, job["course_id"], graph, job["requested_by"], "extraction",
                f"{job['mode']} 抽取：新增 {added_nodes} 个知识点、{added_edges} 条关系；候选图谱共 {len(graph.nodes)} 个知识点{quality_suffix}", "candidate",
            )
            connection.execute(
                """
                UPDATE extraction_jobs SET status = 'review', progress = 100,
                  message = ?, candidate_version_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (f"候选图谱已生成：新增 {added_nodes} 个知识点、{added_edges} 条关系，请教师审核后应用{quality_suffix}", version_id, job_id),
            )
    except Exception as exc:
        with connect() as connection:
            connection.execute(
                "UPDATE extraction_jobs SET status = 'failed', message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(exc), job_id),
            )


def resume_pending_jobs() -> int:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id FROM extraction_jobs WHERE status IN ('queued', 'parsing', 'extracting', 'merging')"
        ).fetchall()
        connection.execute(
            """
            UPDATE extraction_jobs SET status = 'queued', progress = 0,
              message = '服务重启后恢复任务', updated_at = CURRENT_TIMESTAMP
            WHERE status IN ('parsing', 'extracting', 'merging')
            """
        )
    for row in rows:
        process_extraction_job(row["id"])
    return len(rows)


def _extraction_quality_warning(graph: KnowledgeGraph) -> str:
    warnings: list[str] = []
    relation_types = {edge.relation for edge in graph.edges}
    sourced_nodes = sum(bool(node.source_refs) for node in graph.nodes)
    if len(graph.nodes) < 20:
        warnings.append(f"仅抽取 {len(graph.nodes)} 个知识点，未达到 20 个验收目标")
    if len(relation_types) < 3:
        warnings.append(f"仅覆盖 {len(relation_types)} 类关系，未覆盖三类关系")
    if graph.nodes and sourced_nodes / len(graph.nodes) < 0.7:
        warnings.append("少于 70% 的知识点带有可追溯来源")
    return "；".join(warnings)


def get_extraction_job(job_id: str, user: User) -> ExtractionJob:
    with connect() as connection:
        row = connection.execute("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise KeyError("抽取任务不存在")
    _assert_course_read(row["course_id"], user)
    return ExtractionJob(**dict(row))


def list_extraction_jobs(course_id: str, user: User) -> list[ExtractionJob]:
    _assert_course_read(course_id, user)
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM extraction_jobs WHERE course_id = ? ORDER BY created_at DESC LIMIT 20", (course_id,)
        ).fetchall()
    return [ExtractionJob(**dict(row)) for row in rows]


def list_versions(course_id: str, user: User) -> list[GraphVersion]:
    _assert_course_read(course_id, user)
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, course_id, version_no, status, trigger, summary, created_at, created_by FROM graph_versions WHERE course_id = ? ORDER BY version_no DESC",
            (course_id,),
        ).fetchall()
    return [GraphVersion(**dict(row)) for row in rows]


def get_version(course_id: str, version_id: str, user: User) -> GraphVersion:
    _assert_course_read(course_id, user)
    with connect() as connection:
        row = connection.execute("SELECT * FROM graph_versions WHERE id = ? AND course_id = ?", (version_id, course_id)).fetchone()
    if not row:
        raise KeyError("图谱版本不存在")
    values = dict(row)
    values["graph"] = KnowledgeGraph(**json.loads(values.pop("graph_json")))
    return GraphVersion(**values)


def accept_version(course_id: str, version_id: str, user: User) -> GraphVersion:
    _assert_course_manage(course_id, user)
    with connect() as connection:
        row = connection.execute("SELECT * FROM graph_versions WHERE id = ? AND course_id = ?", (version_id, course_id)).fetchone()
        if not row or row["status"] != "candidate":
            raise ValueError("只有待审核的候选版本可以应用")
        graph = KnowledgeGraph(**json.loads(row["graph_json"]))
        existing_node_ids = {item["id"] for item in connection.execute(
            "SELECT id FROM nodes WHERE course_id = ?", (course_id,)
        ).fetchall()}
        existing_edge_ids = {item["id"] for item in connection.execute(
            "SELECT id FROM edges WHERE course_id = ?", (course_id,)
        ).fetchall()}
        existing_node_sources = [dict(item) for item in connection.execute(
            "SELECT * FROM node_sources WHERE node_id IN (SELECT id FROM nodes WHERE course_id = ?)", (course_id,)
        ).fetchall()]
        existing_edge_sources = [dict(item) for item in connection.execute(
            "SELECT * FROM edge_sources WHERE edge_id IN (SELECT id FROM edges WHERE course_id = ?)", (course_id,)
        ).fetchall()]
        job = connection.execute(
            "SELECT document_ids_json FROM extraction_jobs WHERE candidate_version_id = ?", (version_id,)
        ).fetchone()
        document_ids = json.loads(job["document_ids_json"]) if job else []
        unlinked_document_ids = [document_id for document_id in document_ids if not connection.execute(
            "SELECT 1 FROM node_sources WHERE document_id = ? UNION SELECT 1 FROM edge_sources WHERE document_id = ? LIMIT 1",
            (document_id, document_id),
        ).fetchone()]
        source_document_ids = unlinked_document_ids or document_ids
        _activate_graph(connection, course_id, version_id, graph)
        candidate_node_ids = {node.id for node in graph.nodes}
        candidate_edge_ids = {edge.id for edge in graph.edges}
        for source in existing_node_sources:
            if source["node_id"] in candidate_node_ids:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO node_sources(
                      node_id, document_id, source_type, source_excerpt, manual_override, page_no, confidence, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source["node_id"], source["document_id"], source["source_type"], source["source_excerpt"],
                        source["manual_override"], source.get("page_no"), source.get("confidence", 0), source.get("reason", ""),
                    ),
                )
        for source in existing_edge_sources:
            if source["edge_id"] in candidate_edge_ids:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO edge_sources(
                      edge_id, document_id, source_type, manual_override, page_no, confidence, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source["edge_id"], source["document_id"], source["source_type"], source["manual_override"],
                        source.get("page_no"), source.get("confidence", 0), source.get("reason", ""),
                    ),
                )
        source_type = "shared" if len(source_document_ids) > 1 else "aigc"
        for node in graph.nodes:
            references = [ref for ref in node.source_refs if ref.document_id in document_ids]
            fallback_ids = [] if references or node.id in existing_node_ids else source_document_ids
            for reference in references:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO node_sources(
                      node_id, document_id, source_type, source_excerpt, page_no, confidence, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.id, reference.document_id, source_type, reference.excerpt,
                        reference.page_no, reference.confidence, reference.reason,
                    ),
                )
            for document_id in fallback_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO node_sources(node_id, document_id, source_type, source_excerpt) VALUES (?, ?, ?, ?)",
                    (node.id, document_id, source_type, (node.resources[0] if node.resources else "")),
                )
        for edge in graph.edges:
            references = [ref for ref in edge.source_refs if ref.document_id in document_ids]
            fallback_ids = [] if references or edge.id in existing_edge_ids else source_document_ids
            for reference in references:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO edge_sources(
                      edge_id, document_id, source_type, page_no, confidence, reason
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.id, reference.document_id, source_type,
                        reference.page_no, reference.confidence, reference.reason,
                    ),
                )
            for document_id in fallback_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO edge_sources(edge_id, document_id, source_type) VALUES (?, ?, ?)",
                    (edge.id, document_id, source_type),
                )
        connection.execute(
            "UPDATE extraction_jobs SET status = 'completed', message = '候选图谱已审核通过' WHERE candidate_version_id = ?",
            (version_id,),
        )
        _audit(connection, user, "graph.version.accept", "graph_version", version_id, {"course_id": course_id})
    result = get_version(course_id, version_id, user)
    if result.graph:
        from app.services.neo4j_adapter import sync_confirmed_graph
        sync_confirmed_graph(course_id, result.graph, result.id)
    return result


def reject_version(course_id: str, version_id: str, user: User) -> GraphVersion:
    _assert_course_manage(course_id, user)
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE graph_versions SET status = 'rejected' WHERE id = ? AND course_id = ? AND status = 'candidate'",
            (version_id, course_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("只有待审核版本可以驳回")
        connection.execute(
            "UPDATE extraction_jobs SET status = 'completed', message = '候选图谱已驳回' WHERE candidate_version_id = ?",
            (version_id,),
        )
        _audit(connection, user, "graph.version.reject", "graph_version", version_id, {})
    return get_version(course_id, version_id, user)


def restore_version(course_id: str, version_id: str, user: User) -> GraphVersion:
    _assert_course_manage(course_id, user)
    source = get_version(course_id, version_id, user)
    if not source.graph:
        raise ValueError("版本内容为空")
    with connect() as connection:
        restored_id = _create_version(
            connection, course_id, source.graph, user.id, "restore",
            f"恢复至版本 {source.version_no}", "active",
        )
        _activate_graph(connection, course_id, restored_id, source.graph)
        _audit(connection, user, "graph.version.restore", "graph_version", restored_id, {"source": version_id})
    result = get_version(course_id, restored_id, user)
    if result.graph:
        from app.services.neo4j_adapter import sync_confirmed_graph
        sync_confirmed_graph(course_id, result.graph, result.id)
    return result


def capture_active_snapshot(course_id: str, user: User, trigger: str, summary: str) -> str:
    _assert_course_manage(course_id, user)
    with connect() as connection:
        graph = KnowledgeGraph(**_graph_dict(connection, course_id))
        version_id = _create_version(connection, course_id, graph, user.id, trigger, summary, "active")
        connection.execute("UPDATE graph_versions SET status = 'superseded' WHERE course_id = ? AND id != ? AND status = 'active'", (course_id, version_id))
        connection.execute("UPDATE courses SET active_version_id = ? WHERE id = ?", (version_id, course_id))
    from app.services.neo4j_adapter import sync_confirmed_graph
    sync_confirmed_graph(course_id, graph, version_id)
    return version_id


def document_impact(course_id: str, document_id: str, user: User) -> DocumentImpact:
    _assert_course_manage(course_id, user)
    with connect() as connection:
        exists = connection.execute("SELECT 1 FROM documents WHERE id = ? AND course_id = ? AND status = 'active'", (document_id, course_id)).fetchone()
        if not exists:
            raise KeyError("资料不存在")
        removable_nodes = connection.execute(
            """
            SELECT COUNT(*) FROM node_sources ns WHERE ns.document_id = ? AND ns.manual_override = 0
              AND (SELECT COUNT(*) FROM node_sources all_ns WHERE all_ns.node_id = ns.node_id) = 1
            """,
            (document_id,),
        ).fetchone()[0]
        removable_edges = connection.execute(
            """
            SELECT COUNT(*) FROM edge_sources es WHERE es.document_id = ? AND es.manual_override = 0
              AND (SELECT COUNT(*) FROM edge_sources all_es WHERE all_es.edge_id = es.edge_id) = 1
            """,
            (document_id,),
        ).fetchone()[0]
        preserved_manual = connection.execute(
            "SELECT COUNT(DISTINCT node_id) FROM node_sources WHERE document_id = ? AND manual_override = 1", (document_id,)
        ).fetchone()[0]
        shared = connection.execute(
            """
            SELECT COUNT(*) FROM node_sources ns WHERE ns.document_id = ?
              AND (SELECT COUNT(*) FROM node_sources all_ns WHERE all_ns.node_id = ns.node_id) > 1
            """,
            (document_id,),
        ).fetchone()[0]
    return DocumentImpact(
        document_id=document_id, removable_nodes=removable_nodes, removable_edges=removable_edges,
        preserved_manual_nodes=preserved_manual, shared_nodes=shared,
    )


def delete_document(course_id: str, document_id: str, rollback_graph: bool, user: User) -> dict:
    impact = document_impact(course_id, document_id, user)
    storage_path = ""
    with connect() as connection:
        document = connection.execute(
            "SELECT storage_path FROM documents WHERE id = ? AND course_id = ?", (document_id, course_id)
        ).fetchone()
        storage_path = document["storage_path"]
        if rollback_graph:
            removable_node_ids = [row["node_id"] for row in connection.execute(
                """
                SELECT ns.node_id FROM node_sources ns WHERE ns.document_id = ? AND ns.manual_override = 0
                  AND (SELECT COUNT(*) FROM node_sources all_ns WHERE all_ns.node_id = ns.node_id) = 1
                """,
                (document_id,),
            ).fetchall()]
            removable_edge_ids = [row["edge_id"] for row in connection.execute(
                """
                SELECT es.edge_id FROM edge_sources es WHERE es.document_id = ? AND es.manual_override = 0
                  AND (SELECT COUNT(*) FROM edge_sources all_es WHERE all_es.edge_id = es.edge_id) = 1
                """,
                (document_id,),
            ).fetchall()]
            for edge_id in removable_edge_ids:
                connection.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
            for node_id in removable_node_ids:
                connection.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            connection.execute("UPDATE courses SET source_incomplete = 0 WHERE id = ?", (course_id,))
        else:
            connection.execute("UPDATE courses SET source_incomplete = 1 WHERE id = ?", (course_id,))
        chunk_ids = [row["id"] for row in connection.execute("SELECT id FROM document_chunks WHERE document_id = ?", (document_id,)).fetchall()]
        for chunk_id in chunk_ids:
            try:
                connection.execute("DELETE FROM document_chunks_fts WHERE chunk_id = ?", (chunk_id,))
            except Exception:
                pass
        connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        pending_jobs = connection.execute(
            "SELECT id, document_ids_json, candidate_version_id FROM extraction_jobs WHERE course_id = ? AND status = 'review'",
            (course_id,),
        ).fetchall()
        for pending_job in pending_jobs:
            if document_id not in json.loads(pending_job["document_ids_json"]):
                continue
            connection.execute(
                "UPDATE graph_versions SET status = 'rejected' WHERE id = ? AND status = 'candidate'",
                (pending_job["candidate_version_id"],),
            )
            connection.execute(
                "UPDATE extraction_jobs SET status = 'completed', message = '候选图谱因课件发生变化而失效，系统将重新抽取', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (pending_job["id"],),
            )
        graph = KnowledgeGraph(**_graph_dict(connection, course_id))
        version_id = _create_version(
            connection, course_id, graph, user.id, "document_delete",
            f"删除课件并{'同步回滚图谱' if rollback_graph else '保留现有图谱'}", "active",
        )
        connection.execute("UPDATE graph_versions SET status = 'superseded' WHERE course_id = ? AND id != ? AND status = 'active'", (course_id, version_id))
        connection.execute("UPDATE courses SET active_version_id = ? WHERE id = ?", (version_id, course_id))
        _audit(connection, user, "document.delete", "document", document_id, {"rollback_graph": rollback_graph, **impact.model_dump()})
        needs_reextract = bool(connection.execute(
            """
            SELECT 1 FROM documents d WHERE d.course_id = ? AND d.status = 'active'
              AND NOT EXISTS (SELECT 1 FROM node_sources ns WHERE ns.document_id = d.id)
            LIMIT 1
            """,
            (course_id,),
        ).fetchone())
    path = Path(storage_path)
    if path.is_file() and UPLOAD_DIR in path.parents:
        path.unlink()
    from app.services.neo4j_adapter import sync_confirmed_graph
    sync_confirmed_graph(course_id, graph, version_id)
    return {
        "deleted": document_id,
        "rollback_graph": rollback_graph,
        "impact": impact.model_dump(),
        "needs_reextract": needs_reextract,
    }


def graph_quality(course_id: str, user: User) -> GraphQuality:
    _assert_course_read(course_id, user)
    with connect() as connection:
        graph = _graph_dict(connection, course_id)
        source_nodes = connection.execute(
            "SELECT COUNT(DISTINCT ns.node_id) FROM node_sources ns JOIN nodes n ON n.id = ns.node_id WHERE n.course_id = ?", (course_id,)
        ).fetchone()[0]
    names = [node["name"].strip().lower() for node in graph["nodes"]]
    duplicates = len(names) - len(set(names))
    connected = {edge["source"] for edge in graph["edges"]} | {edge["target"] for edge in graph["edges"]}
    isolated = len([node for node in graph["nodes"] if node["id"] not in connected])
    node_count = max(1, len(graph["nodes"]))
    duplicate_rate = round(duplicates / node_count, 3)
    isolated_rate = round(isolated / node_count, 3)
    relation_coverage = round(min(1.0, len(graph["edges"]) / node_count), 3)
    source_coverage = round(source_nodes / node_count, 3)
    score = round(100 * (1 - duplicate_rate) * 0.25 + 100 * (1 - isolated_rate) * 0.25 + 100 * relation_coverage * 0.25 + 100 * source_coverage * 0.25)
    notes: list[str] = []
    if isolated_rate > 0.2:
        notes.append("孤立知识点较多，建议补充前置或相关关系。")
    if source_coverage < 0.8:
        notes.append("部分知识点缺少课件来源，请复核或补充引用。")
    if not notes:
        notes.append("图谱结构和来源覆盖良好。")
    return GraphQuality(
        score=score, duplicate_rate=duplicate_rate, isolated_rate=isolated_rate,
        relation_coverage=relation_coverage, source_coverage=source_coverage, notes=notes,
    )


def sync_neo4j(course_id: str, user: User) -> dict:
    _assert_course_manage(course_id, user)
    from app.services.neo4j_adapter import sync_course_from_sqlite
    return sync_course_from_sqlite(course_id)


def retrieve_evidence(course_id: str, query: str, user: User, limit: int = 5) -> tuple[list[dict], list[KnowledgeNode]]:
    _assert_course_read(course_id, user)
    terms = search_tokens(query)
    evidence: list[dict] = []
    with connect() as connection:
        chunks: list[dict] = []
        query_expression = fts_query(query)
        if query_expression:
            try:
                chunks = [dict(row) for row in connection.execute(
                    """
                    SELECT dc.id AS chunk_id, dc.document_id, dc.content, dc.page_no, d.filename,
                           bm25(document_chunks_fts) AS bm25_score
                    FROM document_chunks_fts
                    JOIN document_chunks dc ON dc.id = document_chunks_fts.chunk_id
                    JOIN documents d ON d.id = dc.document_id
                    WHERE document_chunks_fts MATCH ? AND document_chunks_fts.course_id = ? AND d.status = 'active'
                    ORDER BY bm25(document_chunks_fts) LIMIT ?
                    """,
                    (query_expression, course_id, limit),
                ).fetchall()]
            except Exception:
                chunks = []
        nodes = [dict(row) for row in connection.execute("SELECT * FROM nodes WHERE course_id = ?", (course_id,)).fetchall()]
        edges = [dict(row) for row in connection.execute(
            "SELECT source, target, label FROM edges WHERE course_id = ?", (course_id,)
        ).fetchall()]
    ranked_nodes = sorted(
        nodes,
        key=lambda row: sum(
            max(4, len(term)) for term in terms
            if term in f"{row['name']} {row['definition']} {row['example']}".lower()
        ),
        reverse=True,
    )
    for rank, row in enumerate(chunks[:limit], start=1):
        page = f"（第 {row['page_no']} 页）" if row["page_no"] else ""
        evidence.append({
            "id": row["chunk_id"], "source": f"{row['filename']}{page}", "excerpt": row["content"][:500],
            "type": "document", "document_id": row["document_id"], "page_no": row["page_no"],
            "bm25_score": round(float(row["bm25_score"]), 6), "rank": rank,
        })
    ranked_nodes = [row for row in ranked_nodes if any(
        term in f"{row['name']} {row['definition']} {row['example']}".casefold() for term in terms
    )]
    citations = [
        KnowledgeNode(
            id=row["id"], name=row["name"], type=row["type"], definition=row["definition"],
            example=row["example"], resources=json.loads(row["resources_json"] or "[]"),
        )
        for row in ranked_nodes[:3]
    ]
    for node in citations:
        evidence.append({"source": f"知识点：{node.name}", "excerpt": node.definition, "type": "graph"})
    citation_ids = {node.id for node in citations}
    from app.services.neo4j_adapter import expand_neighbors
    neo4j_neighbors = expand_neighbors(course_id, list(citation_ids), max(1, 8 - len(evidence)))
    if neo4j_neighbors is not None:
        for edge in neo4j_neighbors:
            evidence.append({
                "source": "Neo4j 图谱邻居扩展",
                "excerpt": f"{edge['source_name']} -[{edge['label']}]-> {edge['target_name']}",
                "type": "relation",
                "backend": "neo4j",
                "relation_id": edge["id"],
            })
            if len(evidence) >= 8:
                break
    else:
        for edge in edges:
            if edge["source"] in citation_ids or edge["target"] in citation_ids:
                source = next((node["name"] for node in nodes if node["id"] == edge["source"]), edge["source"])
                target = next((node["name"] for node in nodes if node["id"] == edge["target"]), edge["target"])
                evidence.append({
                    "source": "SQLite 图谱邻居扩展",
                    "excerpt": f"{source} -[{edge['label']}]-> {target}",
                    "type": "relation",
                    "backend": "sqlite",
                })
                if len(evidence) >= 8:
                    break
    return evidence[:8], citations


def graphrag_answer(course_id: str, question: str, user: User) -> QAResult:
    evidence, citations = retrieve_evidence(course_id, question, user)
    answer = deepseek.answer_with_evidence(question, evidence)
    confidence = _qa_confidence(evidence, citations)
    graph_backend = "+neo4j" if any(item.get("backend") == "neo4j" for item in evidence) else ""
    return QAResult(
        answer=answer, citations=citations, confidence=confidence,
        evidence=evidence,
        mode=("deepseek-graphrag" if deepseek.configured() else "offline-graphrag") + graph_backend,
    )


def _qa_confidence(evidence: list[dict], citations: list[KnowledgeNode]) -> str:
    document_scores = [
        float(item["bm25_score"]) for item in evidence
        if item.get("type") == "document" and item.get("bm25_score") is not None
    ]
    if not document_scores:
        return "low"
    strongest = min(document_scores)
    if citations and (len(document_scores) >= 2 or strongest <= -2.0):
        return "high"
    return "medium"


def enrich_learning_path(
    course_id: str,
    result: LearningPathResult,
    user: User,
    mastery_rate: float,
) -> LearningPathResult:
    recommendation_nodes = [item.node for item in result.recommendations]
    query = " ".join(node.name for node in recommendation_nodes)
    evidence, _ = retrieve_evidence(course_id, query, user) if query else ([], [])
    with connect() as connection:
        course = connection.execute("SELECT name FROM courses WHERE id = ?", (course_id,)).fetchone()
    try:
        summary = deepseek.learning_analysis(
            course["name"] if course else "课程", mastery_rate, recommendation_nodes, recommendation_nodes, evidence,
        )
        mode = "deepseek-evidence" if deepseek.configured() else "offline-rule"
    except ValueError:
        summary = deepseek.learning_analysis(
            course["name"] if course else "课程", mastery_rate, recommendation_nodes, recommendation_nodes, evidence,
        ) if not deepseek.configured() else "AI 服务暂不可用，当前路径仍由前置关系规则生成。"
        mode = "offline-fallback"
    if result.mode == "neo4j-rule":
        mode += "+neo4j"
    return result.model_copy(update={"ai_summary": summary, "mode": mode, "evidence": evidence[:4]})


def _create_version(connection, course_id: str, graph: KnowledgeGraph, created_by: str, trigger: str, summary: str, status: str) -> str:
    version_no = connection.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 FROM graph_versions WHERE course_id = ?", (course_id,)
    ).fetchone()[0]
    version_id = f"version_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT INTO graph_versions(id, course_id, version_no, status, trigger, summary, graph_json, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (version_id, course_id, version_no, status, trigger, summary, graph.model_dump_json(), created_by),
    )
    return version_id


def _merge_graphs(base: KnowledgeGraph, incoming: KnowledgeGraph, max_nodes: int = 30) -> tuple[KnowledgeGraph, int, int]:
    nodes = [node.model_copy(deep=True) for node in base.nodes]
    edges = [edge.model_copy(deep=True) for edge in base.edges]
    names = {_normalized_name(node.name): node.id for node in nodes}
    node_ids = {node.id for node in nodes}
    incoming_to_merged: dict[str, str] = {}
    added_nodes = 0

    for node in incoming.nodes:
        normalized = _normalized_name(node.name)
        if not normalized:
            continue
        if normalized in names:
            existing_id = names[normalized]
            incoming_to_merged[node.id] = existing_id
            existing_node = next(item for item in nodes if item.id == existing_id)
            known_refs = {(ref.document_id, ref.page_no, ref.excerpt) for ref in existing_node.source_refs}
            existing_node.source_refs.extend(
                ref for ref in node.source_refs if (ref.document_id, ref.page_no, ref.excerpt) not in known_refs
            )
            continue
        if len(nodes) >= max(max_nodes, len(base.nodes)):
            continue
        copied = node.model_copy(deep=True)
        if copied.id in node_ids:
            copied.id = f"node_{uuid.uuid4().hex[:12]}"
        nodes.append(copied)
        names[normalized] = copied.id
        node_ids.add(copied.id)
        incoming_to_merged[node.id] = copied.id
        added_nodes += 1

    edge_keys = {(edge.source, edge.target, edge.relation) for edge in edges}
    edge_ids = {edge.id for edge in edges}
    added_edges = 0
    max_edges = max(len(base.edges), len(nodes) * 2)
    for edge in incoming.edges:
        source = incoming_to_merged.get(edge.source)
        target = incoming_to_merged.get(edge.target)
        key = (source or "", target or "", edge.relation)
        if not source or not target or source == target or len(edges) >= max_edges:
            continue
        if key in edge_keys:
            existing_edge = next(item for item in edges if (item.source, item.target, item.relation) == key)
            known_refs = {(ref.document_id, ref.page_no, ref.excerpt) for ref in existing_edge.source_refs}
            existing_edge.source_refs.extend(
                ref for ref in edge.source_refs if (ref.document_id, ref.page_no, ref.excerpt) not in known_refs
            )
            continue
        copied = edge.model_copy(deep=True, update={"source": source, "target": target})
        if copied.id in edge_ids:
            copied.id = f"edge_{uuid.uuid4().hex[:12]}"
        edges.append(copied)
        edge_keys.add(key)
        edge_ids.add(copied.id)
        added_edges += 1

    return KnowledgeGraph(nodes=nodes, edges=edges), added_nodes, added_edges


def _normalized_name(name: str) -> str:
    return re.sub(r"[\s\-_]+", "", name).casefold()


def _activate_graph(connection, course_id: str, version_id: str, graph: KnowledgeGraph) -> None:
    progress = [dict(row) for row in connection.execute(
        """
        SELECT p.* FROM class_learning_progress p JOIN classrooms c ON c.id = p.classroom_id
        WHERE c.course_id = ?
        """,
        (course_id,),
    ).fetchall()]
    connection.execute("DELETE FROM edges WHERE course_id = ?", (course_id,))
    connection.execute("DELETE FROM nodes WHERE course_id = ?", (course_id,))
    node_ids = {node.id for node in graph.nodes}
    for node in graph.nodes:
        connection.execute(
            "INSERT INTO nodes(id, course_id, name, type, definition, example, resources_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node.id, course_id, node.name, node.type, node.definition, node.example, json.dumps(node.resources, ensure_ascii=False)),
        )
    for edge in graph.edges:
        if edge.source in node_ids and edge.target in node_ids:
            connection.execute(
                "INSERT INTO edges(id, course_id, source, target, relation, label) VALUES (?, ?, ?, ?, ?, ?)",
                (edge.id, course_id, edge.source, edge.target, edge.relation, edge.label),
            )
    for item in progress:
        if item["node_id"] in node_ids:
            connection.execute(
                """
                INSERT OR REPLACE INTO class_learning_progress(user_id, classroom_id, node_id, mastered, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (item["user_id"], item["classroom_id"], item["node_id"], item["mastered"], item["updated_at"]),
            )
    connection.execute("UPDATE graph_versions SET status = 'superseded' WHERE course_id = ? AND status = 'active'", (course_id,))
    connection.execute("UPDATE graph_versions SET status = 'active' WHERE id = ?", (version_id,))
    connection.execute("UPDATE courses SET active_version_id = ?, source_incomplete = 0 WHERE id = ?", (version_id, course_id))


def _assert_course_manage(course_id: str, user: User) -> None:
    if user.role == "admin":
        return
    if user.role != "teacher" or user.account_status != "active":
        raise PermissionError("无权管理该课程")
    with connect() as connection:
        owner = connection.execute("SELECT owner_id FROM courses WHERE id = ?", (course_id,)).fetchone()
        collaborator = connection.execute(
            """
            SELECT 1 FROM class_teachers ct JOIN classrooms c ON c.id = ct.classroom_id
            WHERE c.course_id = ? AND ct.teacher_id = ? AND ct.can_edit_course = 1
            """,
            (course_id, user.id),
        ).fetchone()
    if not owner:
        raise KeyError("课程不存在")
    if owner["owner_id"] != user.id and not collaborator:
        raise PermissionError("无权管理该课程")


def _assert_course_read(course_id: str, user: User) -> None:
    if user.role == "admin":
        return
    with connect() as connection:
        if user.role == "teacher":
            found = connection.execute(
                """
                SELECT 1 FROM courses c WHERE c.id = ? AND (
                  c.owner_id = ? OR EXISTS (SELECT 1 FROM classrooms cl JOIN class_teachers ct ON ct.classroom_id = cl.id WHERE cl.course_id = c.id AND ct.teacher_id = ?)
                )
                """,
                (course_id, user.id, user.id),
            ).fetchone()
        else:
            found = connection.execute(
                """
                SELECT 1 FROM classrooms c JOIN enrollments e ON e.classroom_id = c.id
                WHERE c.course_id = ? AND e.student_id = ? AND e.status = 'active' AND c.status = 'active'
                """,
                (course_id, user.id),
            ).fetchone()
    if not found:
        raise PermissionError("无权访问该课程")
