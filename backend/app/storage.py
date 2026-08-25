from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from app.models import (
    Course,
    CourseCreate,
    DocumentInfo,
    GraphStats,
    KnowledgeEdge,
    KnowledgeEdgeCreate,
    KnowledgeGraph,
    KnowledgeNode,
    KnowledgeNodeCreate,
)
from app.services.extractor import RELATION_LABELS, build_mock_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "data"
STORE_FILE = DATA_DIR / "store.json"
UPLOAD_DIR = DATA_DIR / "uploads"
SAMPLE_DIR = PROJECT_ROOT / "sample_data"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def init_store(force: bool = False) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if STORE_FILE.exists() and not force:
        return _read_json(STORE_FILE)
    courses = _read_json(SAMPLE_DIR / "courses.json")["courses"]
    graphs: dict[str, dict] = {}
    documents: dict[str, list[dict]] = {}
    for course in courses:
        graph_path = SAMPLE_DIR / "graphs" / f"{course['id']}.json"
        graphs[course["id"]] = _read_json(graph_path)
        documents[course["id"]] = []
    state = {"courses": courses, "graphs": graphs, "documents": documents}
    _write_json(STORE_FILE, state)
    return state


def reset_store() -> dict:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    return init_store(force=True)


def load_state() -> dict:
    return init_store()


def save_state(state: dict) -> None:
    _write_json(STORE_FILE, state)


def graph_stats(graph: dict) -> GraphStats:
    relation_types = {edge["relation"] for edge in graph.get("edges", [])}
    return GraphStats(nodes=len(graph.get("nodes", [])), edges=len(graph.get("edges", [])), relation_types=len(relation_types))


def list_courses() -> list[Course]:
    state = load_state()
    result: list[Course] = []
    for course in state["courses"]:
        graph = state["graphs"].get(course["id"], {"nodes": [], "edges": []})
        result.append(
            Course(
                **course,
                document_count=len(state["documents"].get(course["id"], [])),
                stats=graph_stats(graph),
            )
        )
    return result


def add_course(payload: CourseCreate) -> Course:
    state = load_state()
    course_id = f"course_{uuid.uuid4().hex[:8]}"
    course = {"id": course_id, "name": payload.name, "description": payload.description}
    state["courses"].append(course)
    state["graphs"][course_id] = {"nodes": [], "edges": []}
    state["documents"][course_id] = []
    save_state(state)
    return Course(**course)


def ensure_course(state: dict, course_id: str) -> dict:
    for course in state["courses"]:
        if course["id"] == course_id:
            return course
    raise KeyError("课程不存在")


def get_graph(course_id: str) -> KnowledgeGraph:
    state = load_state()
    ensure_course(state, course_id)
    return KnowledgeGraph(**state["graphs"].get(course_id, {"nodes": [], "edges": []}))


def save_document(course_id: str, filename: str, fmt: str, content: str, raw: bytes) -> DocumentInfo:
    state = load_state()
    ensure_course(state, course_id)
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    course_upload_dir = UPLOAD_DIR / course_id
    course_upload_dir.mkdir(parents=True, exist_ok=True)
    (course_upload_dir / f"{doc_id}_{filename}").write_bytes(raw)
    doc = {
        "id": doc_id,
        "filename": filename,
        "format": fmt,
        "size": len(raw),
        "parsed_chars": len(content),
        "content": content,
    }
    state["documents"].setdefault(course_id, []).append(doc)
    save_state(state)
    return DocumentInfo(**{key: doc[key] for key in ("id", "filename", "format", "size", "parsed_chars")})


def extract_course_graph(course_id: str) -> KnowledgeGraph:
    state = load_state()
    course = ensure_course(state, course_id)
    docs = state["documents"].get(course_id, [])
    graph = build_mock_graph(course["name"], docs)
    state["graphs"][course_id] = graph.model_dump()
    save_state(state)
    return graph


def add_node(course_id: str, payload: KnowledgeNodeCreate) -> KnowledgeNode:
    state = load_state()
    ensure_course(state, course_id)
    node = KnowledgeNode(id=f"node_{uuid.uuid4().hex[:10]}", **payload.model_dump())
    state["graphs"][course_id]["nodes"].append(node.model_dump())
    save_state(state)
    return node


def update_node(course_id: str, node_id: str, payload: KnowledgeNodeCreate) -> KnowledgeNode:
    state = load_state()
    ensure_course(state, course_id)
    nodes = state["graphs"][course_id]["nodes"]
    for index, node in enumerate(nodes):
        if node["id"] == node_id:
            updated = KnowledgeNode(id=node_id, **payload.model_dump())
            nodes[index] = updated.model_dump()
            save_state(state)
            return updated
    raise KeyError("知识点不存在")


def delete_node(course_id: str, node_id: str) -> dict:
    state = load_state()
    ensure_course(state, course_id)
    graph = state["graphs"][course_id]
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] != node_id]
    graph["edges"] = [edge for edge in graph["edges"] if edge["source"] != node_id and edge["target"] != node_id]
    save_state(state)
    return {"deleted": node_id}


def add_edge(course_id: str, payload: KnowledgeEdgeCreate) -> KnowledgeEdge:
    state = load_state()
    ensure_course(state, course_id)
    label = payload.label or RELATION_LABELS[payload.relation]
    edge = KnowledgeEdge(id=f"edge_{uuid.uuid4().hex[:10]}", **payload.model_dump(exclude={"label"}), label=label)
    state["graphs"][course_id]["edges"].append(edge.model_dump())
    save_state(state)
    return edge


def delete_edge(course_id: str, edge_id: str) -> dict:
    state = load_state()
    ensure_course(state, course_id)
    graph = state["graphs"][course_id]
    graph["edges"] = [edge for edge in graph["edges"] if edge["id"] != edge_id]
    save_state(state)
    return {"deleted": edge_id}
