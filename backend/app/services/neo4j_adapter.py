from __future__ import annotations

import os

from app.models import KnowledgeGraph


def configured() -> bool:
    return bool(os.environ.get("NEO4J_HTTP_URL", "").strip())


def sync_confirmed_graph(course_id: str, graph: KnowledgeGraph) -> dict:
    if not configured():
        return {"enabled": False, "synced": False, "message": "Neo4j 未配置，继续使用 SQLite 图谱"}
    try:
        import httpx

        base_url = os.environ["NEO4J_HTTP_URL"].rstrip("/")
        auth = (
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "coursegraph-password"),
        )
        statements = [
            {
                "statement": "MATCH (n:KnowledgeNode {course_id: $course_id}) DETACH DELETE n",
                "parameters": {"course_id": course_id},
            },
            {
                "statement": """
                UNWIND $nodes AS node
                CREATE (:KnowledgeNode {
                  id: node.id, course_id: $course_id, name: node.name, type: node.type,
                  definition: node.definition, example: node.example
                })
                """,
                "parameters": {
                    "course_id": course_id,
                    "nodes": [node.model_dump(exclude={"resources", "mastered"}) for node in graph.nodes],
                },
            },
            {
                "statement": """
                UNWIND $edges AS edge
                MATCH (source:KnowledgeNode {id: edge.source, course_id: $course_id})
                MATCH (target:KnowledgeNode {id: edge.target, course_id: $course_id})
                CREATE (source)-[:COURSE_RELATION {id: edge.id, type: edge.relation, label: edge.label}]->(target)
                """,
                "parameters": {
                    "course_id": course_id,
                    "edges": [edge.model_dump() for edge in graph.edges],
                },
            },
        ]
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{base_url}/db/neo4j/tx/commit",
                auth=auth,
                json={"statements": statements},
            )
        response.raise_for_status()
        errors = response.json().get("errors", [])
        if errors:
            raise RuntimeError(errors[0].get("message", "Neo4j 同步失败"))
        return {"enabled": True, "synced": True, "message": "已同步确认图谱到 Neo4j"}
    except Exception as exc:
        return {"enabled": True, "synced": False, "message": f"Neo4j 不可用，已降级到 SQLite：{exc}"}


def status() -> dict:
    if not configured():
        return {"enabled": False, "available": False, "message": "未配置"}
    try:
        import httpx

        base_url = os.environ["NEO4J_HTTP_URL"].rstrip("/")
        response = httpx.get(base_url, timeout=3.0)
        return {"enabled": True, "available": response.status_code < 500, "message": "已连接"}
    except Exception as exc:
        return {"enabled": True, "available": False, "message": f"连接失败：{exc}"}
