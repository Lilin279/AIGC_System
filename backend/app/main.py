from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import storage
from app.auth import issue_session, revoke_session, user_from_token
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
    LoginRequest,
    LoginResult,
    ProgressUpdate,
    QARequest,
    QAResult,
    RegisterRequest,
    User,
)
from app.services.parser import parse_text_file
from app.services.qa import answer_question
from app.services.recommender import recommend_path


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
bearer = HTTPBearer(auto_error=False)
T = TypeVar("T")

app = FastAPI(
    title="AIGC 课程知识图谱学习导航系统",
    description="课程资料解析、知识图谱、学习路径推荐与可追溯问答平台。",
    version="0.2.0",
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


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="请先登录", headers={"WWW-Authenticate": "Bearer"})
    user = user_from_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录", headers={"WWW-Authenticate": "Bearer"})
    return user


def session_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    return credentials.credentials


def execute(action: Callable[[], T]) -> T:
    try:
        return action()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_message(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _message(exc: KeyError) -> str:
    return str(exc.args[0]) if exc.args else "资源不存在"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": "sqlite", "version": app.version}


@app.post("/api/auth/register", response_model=LoginResult, status_code=201)
def register(payload: RegisterRequest) -> LoginResult:
    user = execute(lambda: storage.register_student(payload))
    token, expires_at = issue_session(user.id)
    return LoginResult(token=token, user=user, expires_at=expires_at)


@app.post("/api/auth/login", response_model=LoginResult)
def login(payload: LoginRequest) -> LoginResult:
    user = storage.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token, expires_at = issue_session(user.id)
    return LoginResult(token=token, user=user, expires_at=expires_at)


@app.get("/api/auth/me", response_model=User)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@app.post("/api/auth/logout", status_code=204)
def logout(token: Annotated[str, Depends(session_token)]) -> None:
    revoke_session(token)


@app.post("/api/admin/reset-demo")
def reset_demo(user: Annotated[User, Depends(current_user)]) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以重置演示数据")
    storage.reset_store()
    return {"status": "reset"}


@app.get("/api/courses", response_model=list[Course])
def list_courses(user: Annotated[User, Depends(current_user)]) -> list[Course]:
    return storage.list_courses(user)


@app.post("/api/courses", response_model=Course, status_code=201)
def create_course(payload: CourseCreate, user: Annotated[User, Depends(current_user)]) -> Course:
    return execute(lambda: storage.add_course(payload, user))


@app.put("/api/courses/{course_id}", response_model=Course)
def update_course(course_id: str, payload: CourseUpdate, user: Annotated[User, Depends(current_user)]) -> Course:
    return execute(lambda: storage.update_course(course_id, payload, user))


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: str, user: Annotated[User, Depends(current_user)]) -> dict:
    return execute(lambda: storage.delete_course(course_id, user))


@app.post("/api/courses/{course_id}/documents", response_model=DocumentInfo, status_code=201)
async def upload_document(
    course_id: str, file: UploadFile = File(...), user: User = Depends(current_user),
) -> DocumentInfo:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="单个文件不能超过 20 MB")
    try:
        content, fmt = parse_text_file(file.filename or "document.txt", raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return execute(lambda: storage.save_document(course_id, file.filename or "document.txt", fmt, content, raw, user))


@app.get("/api/courses/{course_id}/documents", response_model=list[DocumentInfo])
def list_documents(course_id: str, user: Annotated[User, Depends(current_user)]) -> list[DocumentInfo]:
    return execute(lambda: storage.list_documents(course_id, user))


@app.delete("/api/courses/{course_id}/documents/{document_id}")
def delete_document(course_id: str, document_id: str, user: Annotated[User, Depends(current_user)]) -> dict:
    return execute(lambda: storage.delete_document(course_id, document_id, user))


@app.post("/api/courses/{course_id}/extract", response_model=ExtractionResult)
def extract(course_id: str, user: Annotated[User, Depends(current_user)]) -> ExtractionResult:
    graph = execute(lambda: storage.extract_course_graph(course_id, user))
    return ExtractionResult(
        course_id=course_id, status="completed",
        message=f"已生成 {len(graph.nodes)} 个知识点、{len(graph.edges)} 条关系，覆盖包含/前置/相关三类关系。",
        graph=graph,
    )


@app.get("/api/courses/{course_id}/graph", response_model=KnowledgeGraph)
def get_graph(course_id: str, user: Annotated[User, Depends(current_user)]) -> KnowledgeGraph:
    return execute(lambda: storage.get_graph(course_id, user))


@app.post("/api/courses/{course_id}/graph/nodes", response_model=KnowledgeNode, status_code=201)
def add_node(course_id: str, payload: KnowledgeNodeCreate, user: Annotated[User, Depends(current_user)]) -> KnowledgeNode:
    return execute(lambda: storage.add_node(course_id, payload, user))


@app.put("/api/courses/{course_id}/graph/nodes/{node_id}", response_model=KnowledgeNode)
def update_node(
    course_id: str, node_id: str, payload: KnowledgeNodeCreate, user: Annotated[User, Depends(current_user)],
) -> KnowledgeNode:
    return execute(lambda: storage.update_node(course_id, node_id, payload, user))


@app.delete("/api/courses/{course_id}/graph/nodes/{node_id}")
def delete_node(course_id: str, node_id: str, user: Annotated[User, Depends(current_user)]) -> dict:
    return execute(lambda: storage.delete_node(course_id, node_id, user))


@app.post("/api/courses/{course_id}/graph/edges", response_model=KnowledgeEdge, status_code=201)
def add_edge(course_id: str, payload: KnowledgeEdgeCreate, user: Annotated[User, Depends(current_user)]) -> KnowledgeEdge:
    return execute(lambda: storage.add_edge(course_id, payload, user))


@app.put("/api/courses/{course_id}/graph/edges/{edge_id}", response_model=KnowledgeEdge)
def update_edge(
    course_id: str, edge_id: str, payload: KnowledgeEdgeUpdate, user: Annotated[User, Depends(current_user)],
) -> KnowledgeEdge:
    return execute(lambda: storage.update_edge(course_id, edge_id, payload, user))


@app.delete("/api/courses/{course_id}/graph/edges/{edge_id}")
def delete_edge(course_id: str, edge_id: str, user: Annotated[User, Depends(current_user)]) -> dict:
    return execute(lambda: storage.delete_edge(course_id, edge_id, user))


@app.put("/api/courses/{course_id}/progress/{node_id}", response_model=KnowledgeNode)
def update_progress(
    course_id: str, node_id: str, payload: ProgressUpdate, user: Annotated[User, Depends(current_user)],
) -> KnowledgeNode:
    return execute(lambda: storage.set_progress(course_id, node_id, payload.mastered, user))


@app.post("/api/courses/{course_id}/qa", response_model=QAResult)
def qa(course_id: str, payload: QARequest, user: Annotated[User, Depends(current_user)]) -> QAResult:
    graph = execute(lambda: storage.get_graph(course_id, user))
    return answer_question(graph, payload.question)


@app.post("/api/courses/{course_id}/learning-path", response_model=LearningPathResult)
def learning_path(
    course_id: str, payload: LearningPathRequest, user: Annotated[User, Depends(current_user)],
) -> LearningPathResult:
    graph = execute(lambda: storage.get_graph(course_id, user))
    mastered = payload.mastered_node_ids
    if mastered is None:
        mastered = execute(lambda: storage.mastered_node_ids(course_id, user)) if user.role == "student" else []
    return recommend_path(graph, mastered)
