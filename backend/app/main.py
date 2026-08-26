from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    Course,
    CourseCreate,
    CourseUpdate,
    DocumentInfo,
    ExtractionResult,
    KnowledgeEdge,
    KnowledgeEdgeCreate,
    KnowledgeEdgeUpdate,
    KnowledgeGraph,
    KnowledgeNode,
    KnowledgeNodeCreate,
    LearningPathRequest,
    LearningPathResult,
    QARequest,
    QAResult,
    LoginRequest,
    LoginResult,
    User,
)
from app.services.parser import parse_text_file
from app.services.qa import answer_question
from app.services.recommender import recommend_path
from app import storage


app = FastAPI(
    title="AIGC 课程知识图谱学习导航系统",
    description="服务外包竞赛原型：课程资料解析、知识图谱、学习路径推荐与离线 RAG 问答。",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    storage.init_store()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": "offline-demo"}


@app.post("/api/auth/login", response_model=LoginResult)
def login(payload: LoginRequest) -> LoginResult:
    display_name = payload.username.strip() or ("教师用户" if payload.role == "teacher" else "学生用户")
    user = User(id=f"{payload.role}_demo", name=display_name, role=payload.role, organization="金扬智能示范学校")
    return LoginResult(token=f"demo-token-{payload.role}", user=user)


@app.post("/api/admin/reset-demo")
def reset_demo() -> dict:
    storage.reset_store()
    return {"status": "reset"}


@app.get("/api/courses", response_model=list[Course])
def list_courses() -> list[Course]:
    return storage.list_courses()


@app.post("/api/courses", response_model=Course)
def create_course(payload: CourseCreate) -> Course:
    return storage.add_course(payload)


@app.put("/api/courses/{course_id}", response_model=Course)
def update_course(course_id: str, payload: CourseUpdate) -> Course:
    try:
        return storage.update_course(course_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: str) -> dict:
    try:
        return storage.delete_course(course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/courses/{course_id}/documents", response_model=DocumentInfo)
async def upload_document(course_id: str, file: UploadFile = File(...)) -> DocumentInfo:
    raw = await file.read()
    try:
        content, fmt = parse_text_file(file.filename or "document.txt", raw)
        return storage.save_document(course_id, file.filename or "document.txt", fmt, content, raw)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/courses/{course_id}/documents", response_model=list[DocumentInfo])
def list_documents(course_id: str) -> list[DocumentInfo]:
    try:
        return storage.list_documents(course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/courses/{course_id}/documents/{document_id}")
def delete_document(course_id: str, document_id: str) -> dict:
    try:
        return storage.delete_document(course_id, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/courses/{course_id}/extract", response_model=ExtractionResult)
def extract(course_id: str) -> ExtractionResult:
    try:
        graph = storage.extract_course_graph(course_id)
        return ExtractionResult(
            course_id=course_id,
            status="completed",
            message=f"已生成 {len(graph.nodes)} 个知识点、{len(graph.edges)} 条关系，覆盖包含/前置/相关三类关系。",
            graph=graph,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/courses/{course_id}/graph", response_model=KnowledgeGraph)
def get_graph(course_id: str) -> KnowledgeGraph:
    try:
        return storage.get_graph(course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/courses/{course_id}/graph/nodes", response_model=KnowledgeNode)
def add_node(course_id: str, payload: KnowledgeNodeCreate) -> KnowledgeNode:
    try:
        return storage.add_node(course_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/courses/{course_id}/graph/nodes/{node_id}", response_model=KnowledgeNode)
def update_node(course_id: str, node_id: str, payload: KnowledgeNodeCreate) -> KnowledgeNode:
    try:
        return storage.update_node(course_id, node_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/courses/{course_id}/graph/nodes/{node_id}")
def delete_node(course_id: str, node_id: str) -> dict:
    try:
        return storage.delete_node(course_id, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/courses/{course_id}/graph/edges", response_model=KnowledgeEdge)
def add_edge(course_id: str, payload: KnowledgeEdgeCreate) -> KnowledgeEdge:
    try:
        return storage.add_edge(course_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/courses/{course_id}/graph/edges/{edge_id}", response_model=KnowledgeEdge)
def update_edge(course_id: str, edge_id: str, payload: KnowledgeEdgeUpdate) -> KnowledgeEdge:
    try:
        return storage.update_edge(course_id, edge_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/courses/{course_id}/graph/edges/{edge_id}")
def delete_edge(course_id: str, edge_id: str) -> dict:
    try:
        return storage.delete_edge(course_id, edge_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/courses/{course_id}/qa", response_model=QAResult)
def qa(course_id: str, payload: QARequest) -> QAResult:
    try:
        graph = storage.get_graph(course_id)
        return answer_question(graph, payload.question)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/courses/{course_id}/learning-path", response_model=LearningPathResult)
def learning_path(course_id: str, payload: LearningPathRequest) -> LearningPathResult:
    try:
        graph = storage.get_graph(course_id)
        return recommend_path(graph, payload.mastered_node_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
