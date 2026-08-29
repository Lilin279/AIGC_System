from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import UPLOAD_DIR, connect  # noqa: E402
from app.graph_lifecycle import _activate_graph, _create_version  # noqa: E402
from app.models import KnowledgeGraph  # noqa: E402


def restore(course_id: str, clean: bool = False) -> tuple[int, int, int]:
    graph_path = ROOT / "sample_data" / "graphs" / f"{course_id}.json"
    if not graph_path.exists():
        raise SystemExit(f"示例图谱不存在：{graph_path}")
    graph = KnowledgeGraph(**json.loads(graph_path.read_text(encoding="utf-8")))

    with connect() as connection:
        course = connection.execute("SELECT owner_id FROM courses WHERE id = ?", (course_id,)).fetchone()
        if not course:
            raise SystemExit(f"课程不存在：{course_id}")
        if clean:
            connection.execute(
                "UPDATE courses SET active_version_id = '', source_incomplete = 0 WHERE id = ?", (course_id,)
            )
            connection.execute("DELETE FROM extraction_jobs WHERE course_id = ?", (course_id,))
            connection.execute("DELETE FROM graph_versions WHERE course_id = ?", (course_id,))
            connection.execute(
                "DELETE FROM documents WHERE course_id = ? AND id NOT LIKE 'sample_%'", (course_id,)
            )
        sample_document = connection.execute(
            "SELECT id FROM documents WHERE course_id = ? AND id LIKE 'sample_%' LIMIT 1", (course_id,)
        ).fetchone()
        version_id = _create_version(
            connection, course_id, graph, course["owner_id"], "sample_restore",
            "恢复内置示例图谱，移除误传课件造成的内容", "active",
        )
        _activate_graph(connection, course_id, version_id, graph)
        if sample_document:
            for node in graph.nodes:
                connection.execute(
                    "INSERT OR IGNORE INTO node_sources(node_id, document_id, source_type, source_excerpt) VALUES (?, ?, 'aigc', ?)",
                    (node.id, sample_document["id"], node.resources[0] if node.resources else ""),
                )
            for edge in graph.edges:
                connection.execute(
                    "INSERT OR IGNORE INTO edge_sources(edge_id, document_id, source_type) VALUES (?, ?, 'aigc')",
                    (edge.id, sample_document["id"]),
                )
        referenced_paths = {
            Path(row["storage_path"]).resolve()
            for row in connection.execute("SELECT storage_path FROM documents WHERE storage_path != ''").fetchall()
        }

    removed_files = 0
    upload_root = UPLOAD_DIR.resolve()
    if upload_root.exists():
        for path in upload_root.rglob("*"):
            resolved = path.resolve()
            if path.is_file() and upload_root in resolved.parents and resolved not in referenced_paths:
                path.unlink()
                removed_files += 1
    return len(graph.nodes), len(graph.edges), removed_files


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="恢复一门内置课程的示例图谱")
    parser.add_argument("course_id", choices=["python_intro", "database_systems"])
    parser.add_argument(
        "--clean", action="store_true", help="同时清除该课程的上传课件、抽取任务和版本历史"
    )
    args = parser.parse_args()
    nodes, edges, removed = restore(args.course_id, clean=args.clean)
    print(f"已恢复 {args.course_id}：{nodes} 个知识点、{edges} 条关系；清理 {removed} 个孤立上传文件。")
