from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from app.database import connect
from app.models import KnowledgeEdge, KnowledgeGraph, KnowledgeNode


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def configured() -> bool:
    return bool(os.environ.get("NEO4J_HTTP_URL", "").strip())


def _database() -> str:
    value = os.environ.get("NEO4J_DATABASE", "neo4j").strip() or "neo4j"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError("NEO4J_DATABASE 包含非法字符")
    return value


def _transaction_url() -> str:
    return f"{os.environ['NEO4J_HTTP_URL'].rstrip('/')}/db/{quote(_database(), safe='')}/tx/commit"


def _auth() -> tuple[str, str]:
    return (
        os.environ.get("NEO4J_USER", "neo4j").strip() or "neo4j",
        os.environ.get("NEO4J_PASSWORD", ""),
    )


def _execute(statements: list[dict[str, Any]], timeout: float = 8.0) -> list[dict[str, Any]]:
    import httpx

    response = None
    for attempt in range(3):
        try:
            # 图数据库凭据不应被系统 HTTP 代理转发，localhost 也常因代理产生伪 502。
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.post(_transaction_url(), auth=_auth(), json={"statements": statements})
            response.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = isinstance(exc, httpx.TransportError) or (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            )
            if not retryable or attempt == 2:
                raise
            time.sleep(0.2 * (2 ** attempt))
    if response is None:
        raise RuntimeError("Neo4j 未返回响应")
    payload = response.json()
    errors = payload.get("errors", [])
    if errors:
        first = errors[0]
        raise RuntimeError(f"{first.get('code', 'Neo4jError')}: {first.get('message', 'Neo4j 请求失败')}")
    return payload.get("results", [])


def _row(result: dict[str, Any]) -> dict[str, Any]:
    columns = result.get("columns", [])
    data = result.get("data", [])
    values = data[0].get("row", []) if data else []
    return dict(zip(columns, values))


def _record_state(
    course_id: str,
    version_id: str,
    state: str,
    graph: KnowledgeGraph,
    message: str,
    neo4j_nodes: int = 0,
    neo4j_edges: int = 0,
) -> None:
    synced_at = datetime.now(timezone.utc).isoformat() if state == "synced" else None
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO neo4j_sync_state(
              course_id, version_id, status, attempts, sqlite_nodes, sqlite_edges,
              neo4j_nodes, neo4j_edges, message, updated_at, synced_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(course_id) DO UPDATE SET
              version_id = excluded.version_id,
              status = excluded.status,
              attempts = CASE WHEN excluded.status = 'syncing' THEN neo4j_sync_state.attempts + 1 ELSE neo4j_sync_state.attempts END,
              sqlite_nodes = excluded.sqlite_nodes,
              sqlite_edges = excluded.sqlite_edges,
              neo4j_nodes = excluded.neo4j_nodes,
              neo4j_edges = excluded.neo4j_edges,
              message = excluded.message,
              updated_at = CURRENT_TIMESTAMP,
              synced_at = COALESCE(excluded.synced_at, neo4j_sync_state.synced_at)
            """,
            (
                course_id, version_id, state, len(graph.nodes), len(graph.edges),
                neo4j_nodes, neo4j_edges, message[:1000], synced_at,
            ),
        )


def mark_pending(course_id: str, graph: KnowledgeGraph, version_id: str = "") -> None:
    if configured():
        _record_state(course_id, version_id, "pending", graph, "等待同步到 Neo4j")


def sync_confirmed_graph(course_id: str, graph: KnowledgeGraph, version_id: str = "") -> dict[str, Any]:
    if not configured():
        return {"enabled": False, "synced": False, "message": "Neo4j 未配置，继续使用 SQLite 图谱"}
    _record_state(course_id, version_id, "syncing", graph, "正在同步到 Neo4j")
    try:
        nodes = [
            {
                "id": node.id, "name": node.name, "type": node.type,
                "definition": node.definition, "example": node.example, "resources": node.resources,
            }
            for node in graph.nodes
        ]
        edges = [
            {
                "id": edge.id, "source": edge.source, "target": edge.target,
                "relation": edge.relation, "label": edge.label,
            }
            for edge in graph.edges
        ]
        _execute(
            [
                {
                    "statement": "MATCH (n:KnowledgeNode {course_id: $course_id}) DETACH DELETE n",
                    "parameters": {"course_id": course_id},
                },
                {
                    "statement": """
                    UNWIND $nodes AS node
                    CREATE (:KnowledgeNode {
                      id: node.id, course_id: $course_id, graph_version: $version_id,
                      managed_by: 'coursegraph-ai',
                      name: node.name, type: node.type, definition: node.definition,
                      example: node.example, resources: node.resources
                    })
                    """,
                    "parameters": {"course_id": course_id, "version_id": version_id, "nodes": nodes},
                },
                {
                    "statement": """
                    UNWIND $edges AS edge
                    MATCH (source:KnowledgeNode {id: edge.source, course_id: $course_id})
                    MATCH (target:KnowledgeNode {id: edge.target, course_id: $course_id})
                    CREATE (source)-[:COURSE_RELATION {
                      id: edge.id, course_id: $course_id, graph_version: $version_id,
                      managed_by: 'coursegraph-ai',
                      type: edge.relation, label: edge.label
                    }]->(target)
                    """,
                    "parameters": {"course_id": course_id, "version_id": version_id, "edges": edges},
                },
                {
                    "statement": """
                    MERGE (sync:CourseGraphSync {course_id: $course_id})
                    SET sync.managed_by = 'coursegraph-ai', sync.version_id = $version_id, sync.node_count = size($nodes),
                        sync.edge_count = size($edges), sync.synced_at = datetime()
                    """,
                    "parameters": {
                        "course_id": course_id, "version_id": version_id,
                        "nodes": nodes, "edges": edges,
                    },
                },
            ],
            timeout=12.0,
        )
        check = verify_course(course_id, graph, version_id)
        if not check["consistent"]:
            raise RuntimeError(
                f"一致性校验失败：SQLite {len(graph.nodes)}/{len(graph.edges)}，"
                f"Neo4j {check['neo4j_nodes']}/{check['neo4j_edges']}"
            )
        message = f"已同步并校验 {check['neo4j_nodes']} 个节点、{check['neo4j_edges']} 条关系"
        _record_state(
            course_id, version_id, "synced", graph, message,
            check["neo4j_nodes"], check["neo4j_edges"],
        )
        return {"enabled": True, "synced": True, "message": message, **check}
    except Exception as exc:
        message = f"Neo4j 同步失败，业务已降级到 SQLite：{exc}"
        _record_state(course_id, version_id, "failed", graph, message)
        return {"enabled": True, "synced": False, "message": message}


def verify_course(
    course_id: str,
    graph: KnowledgeGraph | None = None,
    version_id: str = "",
) -> dict[str, Any]:
    results = _execute(
        [
            {
                "statement": "MATCH (n:KnowledgeNode {course_id: $course_id}) RETURN count(n) AS node_count",
                "parameters": {"course_id": course_id},
            },
            {
                "statement": "MATCH (:KnowledgeNode {course_id: $course_id})-[r:COURSE_RELATION]->(:KnowledgeNode {course_id: $course_id}) RETURN count(r) AS edge_count",
                "parameters": {"course_id": course_id},
            },
            {
                "statement": "MATCH (s:CourseGraphSync {course_id: $course_id}) RETURN s.version_id AS version_id",
                "parameters": {"course_id": course_id},
            },
        ]
    )
    neo4j_nodes = int(_row(results[0]).get("node_count", 0))
    neo4j_edges = int(_row(results[1]).get("edge_count", 0))
    remote_version = str(_row(results[2]).get("version_id", ""))
    consistent = graph is None or (
        neo4j_nodes == len(graph.nodes)
        and neo4j_edges == len(graph.edges)
        and (not version_id or remote_version == version_id)
    )
    return {
        "consistent": consistent,
        "neo4j_nodes": neo4j_nodes,
        "neo4j_edges": neo4j_edges,
        "version_id": remote_version,
    }


def _sqlite_graph(course_id: str) -> KnowledgeGraph:
    with connect() as connection:
        nodes = [
            KnowledgeNode(
                id=row["id"], name=row["name"], type=row["type"], definition=row["definition"],
                example=row["example"], resources=json.loads(row["resources_json"] or "[]"),
            )
            for row in connection.execute(
                "SELECT * FROM nodes WHERE course_id = ? ORDER BY created_at, id", (course_id,)
            ).fetchall()
        ]
        edges = [
            KnowledgeEdge(**dict(row))
            for row in connection.execute(
                "SELECT id, source, target, relation, label FROM edges WHERE course_id = ? ORDER BY created_at, id",
                (course_id,),
            ).fetchall()
        ]
    return KnowledgeGraph(nodes=nodes, edges=edges)


def sync_course_from_sqlite(course_id: str) -> dict[str, Any]:
    with connect() as connection:
        row = connection.execute("SELECT active_version_id FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not row:
        raise KeyError("课程不存在")
    return sync_confirmed_graph(course_id, _sqlite_graph(course_id), row["active_version_id"] or "")


def sync_all_confirmed_graphs(only_pending: bool = False) -> dict[str, Any]:
    if not configured():
        return {"enabled": False, "total": 0, "synced": 0, "failed": 0, "results": []}
    with connect() as connection:
        where = """
        WHERE s.course_id IS NULL OR s.status != 'synced'
           OR s.version_id != c.active_version_id
           OR s.sqlite_nodes != (SELECT COUNT(*) FROM nodes n WHERE n.course_id = c.id)
           OR s.sqlite_edges != (SELECT COUNT(*) FROM edges e WHERE e.course_id = c.id)
        """ if only_pending else ""
        rows = connection.execute(
            f"""
            SELECT c.id FROM courses c
            LEFT JOIN neo4j_sync_state s ON s.course_id = c.id
            {where}
            ORDER BY c.updated_at, c.id
            """
        ).fetchall()
    results = [{"course_id": row["id"], **sync_course_from_sqlite(row["id"])} for row in rows]
    return {
        "enabled": True,
        "total": len(results),
        "synced": sum(bool(item.get("synced")) for item in results),
        "failed": sum(not bool(item.get("synced")) for item in results),
        "results": results,
    }


def retry_pending_syncs() -> dict[str, Any]:
    return sync_all_confirmed_graphs(only_pending=True)


def remove_course_graph(course_id: str) -> dict[str, Any]:
    if not configured():
        return {"enabled": False, "deleted": False}
    try:
        _execute(
            [
                {
                    "statement": "MATCH (n:KnowledgeNode {course_id: $course_id}) DETACH DELETE n",
                    "parameters": {"course_id": course_id},
                },
                {
                    "statement": "MATCH (s:CourseGraphSync {course_id: $course_id}) DELETE s",
                    "parameters": {"course_id": course_id},
                },
            ]
        )
        return {"enabled": True, "deleted": True}
    except Exception as exc:
        return {"enabled": True, "deleted": False, "message": str(exc)}


def _course_is_synced(course_id: str) -> bool:
    states = sync_state(course_id)
    if not states or states[0]["status"] != "synced":
        return False
    state = states[0]
    with connect() as connection:
        node_count = connection.execute(
            "SELECT COUNT(*) FROM nodes WHERE course_id = ?", (course_id,)
        ).fetchone()[0]
        edge_count = connection.execute(
            "SELECT COUNT(*) FROM edges WHERE course_id = ?", (course_id,)
        ).fetchone()[0]
        version = connection.execute(
            "SELECT active_version_id FROM courses WHERE id = ?", (course_id,)
        ).fetchone()
    return bool(
        version
        and state["version_id"] == (version["active_version_id"] or "")
        and state["sqlite_nodes"] == node_count == state["neo4j_nodes"]
        and state["sqlite_edges"] == edge_count == state["neo4j_edges"]
    )


def prerequisite_edges(course_id: str) -> list[KnowledgeEdge] | None:
    if not configured() or not _course_is_synced(course_id):
        return None
    try:
        results = _execute(
            [
                {
                    "statement": """
                    MATCH (source:KnowledgeNode {course_id: $course_id})-[r:COURSE_RELATION {type: 'prerequisite'}]->(target:KnowledgeNode {course_id: $course_id})
                    RETURN r.id AS id, source.id AS source, target.id AS target, r.type AS relation, r.label AS label
                    ORDER BY r.id
                    """,
                    "parameters": {"course_id": course_id},
                    "resultDataContents": ["row"],
                }
            ]
        )
        result = results[0]
        columns = result.get("columns", [])
        return [KnowledgeEdge(**dict(zip(columns, item.get("row", [])))) for item in result.get("data", [])]
    except Exception:
        return None


def expand_neighbors(course_id: str, node_ids: list[str], limit: int = 5) -> list[dict[str, Any]] | None:
    if not configured() or not node_ids or not _course_is_synced(course_id):
        return None
    try:
        results = _execute(
            [
                {
                    "statement": """
                    MATCH path=(matched:KnowledgeNode {course_id: $course_id})-[:COURSE_RELATION*1..2]-(neighbor:KnowledgeNode {course_id: $course_id})
                    WHERE matched.id IN $node_ids
                    UNWIND relationships(path) AS r
                    WITH r, startNode(r) AS source, endNode(r) AS target, min(length(path)) AS hop
                    RETURN r.id AS id, source.id AS source_id, source.name AS source_name,
                           target.id AS target_id, target.name AS target_name,
                           r.type AS relation, r.label AS label, hop
                    ORDER BY hop, r.id LIMIT $limit
                    """,
                    "parameters": {"course_id": course_id, "node_ids": node_ids, "limit": max(1, min(limit, 20))},
                    "resultDataContents": ["row"],
                }
            ]
        )
        result = results[0]
        columns = result.get("columns", [])
        return [dict(zip(columns, item.get("row", []))) for item in result.get("data", [])]
    except Exception:
        return None


def sync_state(course_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as connection:
        if course_id:
            rows = connection.execute(
                "SELECT * FROM neo4j_sync_state WHERE course_id = ?", (course_id,)
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM neo4j_sync_state ORDER BY updated_at DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def status() -> dict[str, Any]:
    if not configured():
        return {
            "enabled": False, "available": False, "database": _database(),
            "message": "未配置", "sync": {"synced": 0, "pending": 0, "syncing": 0, "failed": 0},
        }
    states = sync_state()
    counts = {
        name: sum(item["status"] == name for item in states)
        for name in ("synced", "pending", "syncing", "failed")
    }
    try:
        results = _execute(
            [
                {"statement": "MATCH (n:KnowledgeNode {managed_by: 'coursegraph-ai'}) RETURN count(n) AS nodes"},
                {"statement": "MATCH (:KnowledgeNode {managed_by: 'coursegraph-ai'})-[r:COURSE_RELATION {managed_by: 'coursegraph-ai'}]->(:KnowledgeNode {managed_by: 'coursegraph-ai'}) RETURN count(r) AS edges"},
            ],
            timeout=4.0,
        )
        return {
            "enabled": True, "available": True, "database": _database(),
            "message": "认证与 Cypher 查询正常",
            "nodes": int(_row(results[0]).get("nodes", 0)),
            "edges": int(_row(results[1]).get("edges", 0)),
            "sync": counts,
        }
    except Exception as exc:
        return {
            "enabled": True, "available": False, "database": _database(),
            "message": f"连接或认证失败：{exc}", "sync": counts,
        }
