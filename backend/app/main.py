from __future__ import annotations

from collections.abc import Callable
from threading import Thread
from typing import Annotated, TypeVar

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse

from app import graph_lifecycle, platform, storage
from app.auth import issue_session, revoke_session, user_from_token
from app.models import (
    AIStatus, AdminUserUpdate, ClassPrimaryTeacherUpdate, ClassTeacherAssign, Classroom, ClassroomCreate, ClassroomUpdate,
    Course, CourseCreate, CourseUpdate, DashboardStats, DiagnosisResult, DocumentImpact,
    DocumentInfo, EnrollmentCreate, ExerciseGenerateRequest, ExerciseResult, ExtractionJob, GraphQuality, GraphVersion,
    ImportCommitResult, ImportPreview, JoinClassRequest, KnowledgeEdge, KnowledgeEdgeCreate,
    KnowledgeEdgeUpdate, KnowledgeGraph, KnowledgeNode, KnowledgeNodeCreate, LearningPathRequest,
    LearningPathResult, LoginRequest, LoginResult, PasswordUpdate, ProfileUpdate, ProgressUpdate,
    QARequest, QAResult, RegisterRequest, TeacherRegisterRequest, TeacherReview, Ticket,
    TicketCreate, TicketReplyCreate, TicketUpdate, User,
)
from app.services import deepseek
from app.services.parser import parse_text_file
from app.services.recommender import recommend_path_for_course


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMPORT_BYTES = 5 * 1024 * 1024
bearer = HTTPBearer(auto_error=False)
T = TypeVar("T")

app = FastAPI(
    title="AIGC 课程知识图谱学习导航系统",
    description="面向学校的课程、教学班、可溯源图谱与个性化学习平台。",
    version="0.5.0",
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
    graph_lifecycle.resume_pending_jobs()
    from app.services.neo4j_adapter import configured as neo4j_configured, retry_pending_syncs
    if neo4j_configured():
        Thread(target=retry_pending_syncs, name="neo4j-sync-retry", daemon=True).start()


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="请先登录", headers={"WWW-Authenticate": "Bearer"})
    user = user_from_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录", headers={"WWW-Authenticate": "Bearer"})
    return user


def operational_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.account_status != "active":
        raise HTTPException(status_code=403, detail="账号尚未通过审核，当前仅可使用个人中心和反馈工单")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="首次登录请先修改临时密码")
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
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "资源不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "storage": "sqlite", "aigc_mode": deepseek.extraction_mode(), "version": app.version}


@app.get("/api/ai/status", response_model=AIStatus)
def ai_status(user: Annotated[User, Depends(operational_user)]) -> AIStatus:
    return AIStatus(**deepseek.status())


# Authentication and profile
@app.post("/api/auth/register", response_model=LoginResult, status_code=201)
def register(payload: RegisterRequest) -> LoginResult:
    user = execute(lambda: storage.register_student(payload))
    token, expires_at = issue_session(user.id)
    return LoginResult(token=token, user=user, expires_at=expires_at)


@app.post("/api/auth/register/teacher", response_model=LoginResult, status_code=201)
def register_teacher(payload: TeacherRegisterRequest) -> LoginResult:
    user = execute(lambda: platform.register_teacher(payload))
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


@app.put("/api/profile", response_model=User)
def update_profile(payload: ProfileUpdate, user: Annotated[User, Depends(current_user)]) -> User:
    return execute(lambda: platform.update_profile(user, payload))


@app.put("/api/profile/password", status_code=204)
def update_password(payload: PasswordUpdate, user: Annotated[User, Depends(current_user)]) -> None:
    execute(lambda: platform.update_password(user, payload))


@app.post("/api/profile/avatar", response_model=User)
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user)) -> User:
    raw = await file.read(2 * 1024 * 1024 + 1)
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="头像不能为空且不能超过 2 MB")
    return execute(lambda: platform.save_avatar(file.filename or "avatar.png", raw, user))


@app.post("/api/auth/logout", status_code=204)
def logout(token: Annotated[str, Depends(session_token)]) -> None:
    revoke_session(token)


# Courses and source documents
@app.get("/api/courses", response_model=list[Course])
def list_courses(user: Annotated[User, Depends(operational_user)]) -> list[Course]:
    return storage.list_courses(user)


@app.post("/api/courses", response_model=Course, status_code=201)
def create_course(payload: CourseCreate, user: Annotated[User, Depends(operational_user)]) -> Course:
    return execute(lambda: storage.add_course(payload, user))


@app.put("/api/courses/{course_id}", response_model=Course)
def update_course(course_id: str, payload: CourseUpdate, user: Annotated[User, Depends(operational_user)]) -> Course:
    return execute(lambda: storage.update_course(course_id, payload, user))


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: str, user: Annotated[User, Depends(operational_user)]) -> dict:
    return execute(lambda: storage.delete_course(course_id, user))


@app.post("/api/courses/{course_id}/documents", response_model=DocumentInfo, status_code=201)
async def upload_document(course_id: str, file: UploadFile = File(...), user: User = Depends(operational_user)) -> DocumentInfo:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="单个文件不能超过 20 MB")
    try:
        content, fmt = parse_text_file(file.filename or "document.txt", raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not content.strip():
        raise HTTPException(status_code=400, detail="未能从课件中提取文字；扫描版 PDF 请先启用 OCR")
    document = execute(lambda: storage.save_document(course_id, file.filename or "document.txt", fmt, content, raw, user))
    execute(lambda: graph_lifecycle.document_saved(document.id, course_id, content, user))
    return document


@app.get("/api/courses/{course_id}/documents", response_model=list[DocumentInfo])
def list_documents(course_id: str, user: Annotated[User, Depends(operational_user)]) -> list[DocumentInfo]:
    return execute(lambda: storage.list_documents(course_id, user))


@app.get("/api/courses/{course_id}/documents/{document_id}/impact", response_model=DocumentImpact)
def document_impact(course_id: str, document_id: str, user: Annotated[User, Depends(operational_user)]) -> DocumentImpact:
    return execute(lambda: graph_lifecycle.document_impact(course_id, document_id, user))


@app.delete("/api/courses/{course_id}/documents/{document_id}")
def delete_document(
    course_id: str, document_id: str, rollback_graph: bool = Query(True),
    user: User = Depends(operational_user),
) -> dict:
    return execute(lambda: graph_lifecycle.delete_document(course_id, document_id, rollback_graph, user))


# Persistent extraction and graph versions
@app.post("/api/courses/{course_id}/extract", response_model=ExtractionJob, status_code=202)
def extract(course_id: str, background_tasks: BackgroundTasks, user: Annotated[User, Depends(operational_user)]) -> ExtractionJob:
    job = execute(lambda: graph_lifecycle.create_extraction_job(course_id, user))
    background_tasks.add_task(graph_lifecycle.process_extraction_job, job.id)
    return job


@app.get("/api/courses/{course_id}/extraction-jobs", response_model=list[ExtractionJob])
def extraction_jobs(course_id: str, user: Annotated[User, Depends(operational_user)]) -> list[ExtractionJob]:
    return execute(lambda: graph_lifecycle.list_extraction_jobs(course_id, user))


@app.get("/api/extraction-jobs/{job_id}", response_model=ExtractionJob)
def extraction_job(job_id: str, user: Annotated[User, Depends(operational_user)]) -> ExtractionJob:
    return execute(lambda: graph_lifecycle.get_extraction_job(job_id, user))


@app.get("/api/courses/{course_id}/graph/versions", response_model=list[GraphVersion])
def graph_versions(course_id: str, user: Annotated[User, Depends(operational_user)]) -> list[GraphVersion]:
    return execute(lambda: graph_lifecycle.list_versions(course_id, user))


@app.get("/api/courses/{course_id}/graph/versions/{version_id}", response_model=GraphVersion)
def graph_version(course_id: str, version_id: str, user: Annotated[User, Depends(operational_user)]) -> GraphVersion:
    return execute(lambda: graph_lifecycle.get_version(course_id, version_id, user))


@app.post("/api/courses/{course_id}/graph/versions/{version_id}/accept", response_model=GraphVersion)
def accept_graph_version(course_id: str, version_id: str, user: Annotated[User, Depends(operational_user)]) -> GraphVersion:
    return execute(lambda: graph_lifecycle.accept_version(course_id, version_id, user))


@app.post("/api/courses/{course_id}/graph/versions/{version_id}/reject", response_model=GraphVersion)
def reject_graph_version(course_id: str, version_id: str, user: Annotated[User, Depends(operational_user)]) -> GraphVersion:
    return execute(lambda: graph_lifecycle.reject_version(course_id, version_id, user))


@app.post("/api/courses/{course_id}/graph/versions/{version_id}/restore", response_model=GraphVersion)
def restore_graph_version(course_id: str, version_id: str, user: Annotated[User, Depends(operational_user)]) -> GraphVersion:
    return execute(lambda: graph_lifecycle.restore_version(course_id, version_id, user))


@app.get("/api/courses/{course_id}/graph/quality", response_model=GraphQuality)
def graph_quality(course_id: str, user: Annotated[User, Depends(operational_user)]) -> GraphQuality:
    return execute(lambda: graph_lifecycle.graph_quality(course_id, user))


# Graph editing and compatibility APIs
@app.get("/api/courses/{course_id}/graph", response_model=KnowledgeGraph)
def get_graph(course_id: str, user: Annotated[User, Depends(operational_user)]) -> KnowledgeGraph:
    return execute(lambda: storage.get_graph(course_id, user))


@app.post("/api/courses/{course_id}/graph/nodes", response_model=KnowledgeNode, status_code=201)
def add_node(course_id: str, payload: KnowledgeNodeCreate, user: Annotated[User, Depends(operational_user)]) -> KnowledgeNode:
    node = execute(lambda: storage.add_node(course_id, payload, user))
    execute(lambda: graph_lifecycle.capture_active_snapshot(course_id, user, "manual", f"新增知识点：{node.name}"))
    return node


@app.put("/api/courses/{course_id}/graph/nodes/{node_id}", response_model=KnowledgeNode)
def update_node(
    course_id: str, node_id: str, payload: KnowledgeNodeCreate,
    user: Annotated[User, Depends(operational_user)],
) -> KnowledgeNode:
    node = execute(lambda: storage.update_node(course_id, node_id, payload, user))
    execute(lambda: graph_lifecycle.capture_active_snapshot(course_id, user, "manual", f"修改知识点：{node.name}"))
    return node


@app.delete("/api/courses/{course_id}/graph/nodes/{node_id}")
def delete_node(course_id: str, node_id: str, user: Annotated[User, Depends(operational_user)]) -> dict:
    result = execute(lambda: storage.delete_node(course_id, node_id, user))
    execute(lambda: graph_lifecycle.capture_active_snapshot(course_id, user, "manual", "删除知识点"))
    return result


@app.post("/api/courses/{course_id}/graph/edges", response_model=KnowledgeEdge, status_code=201)
def add_edge(course_id: str, payload: KnowledgeEdgeCreate, user: Annotated[User, Depends(operational_user)]) -> KnowledgeEdge:
    edge = execute(lambda: storage.add_edge(course_id, payload, user))
    execute(lambda: graph_lifecycle.capture_active_snapshot(course_id, user, "manual", "新增知识关系"))
    return edge


@app.put("/api/courses/{course_id}/graph/edges/{edge_id}", response_model=KnowledgeEdge)
def update_edge(
    course_id: str, edge_id: str, payload: KnowledgeEdgeUpdate,
    user: Annotated[User, Depends(operational_user)],
) -> KnowledgeEdge:
    edge = execute(lambda: storage.update_edge(course_id, edge_id, payload, user))
    execute(lambda: graph_lifecycle.capture_active_snapshot(course_id, user, "manual", "修改知识关系"))
    return edge


@app.delete("/api/courses/{course_id}/graph/edges/{edge_id}")
def delete_edge(course_id: str, edge_id: str, user: Annotated[User, Depends(operational_user)]) -> dict:
    result = execute(lambda: storage.delete_edge(course_id, edge_id, user))
    execute(lambda: graph_lifecycle.capture_active_snapshot(course_id, user, "manual", "删除知识关系"))
    return result


@app.put("/api/courses/{course_id}/progress/{node_id}", response_model=KnowledgeNode)
def update_progress(
    course_id: str, node_id: str, payload: ProgressUpdate,
    user: Annotated[User, Depends(operational_user)],
) -> KnowledgeNode:
    return execute(lambda: storage.set_progress(course_id, node_id, payload.mastered, user))


@app.post("/api/courses/{course_id}/qa", response_model=QAResult)
def qa(course_id: str, payload: QARequest, user: Annotated[User, Depends(operational_user)]) -> QAResult:
    return execute(lambda: graph_lifecycle.graphrag_answer(course_id, payload.question, user))


@app.post("/api/courses/{course_id}/learning-path", response_model=LearningPathResult)
def learning_path(
    course_id: str, payload: LearningPathRequest, user: Annotated[User, Depends(operational_user)],
) -> LearningPathResult:
    graph = execute(lambda: storage.get_graph(course_id, user))
    mastered = payload.mastered_node_ids
    if mastered is None:
        mastered = execute(lambda: storage.mastered_node_ids(course_id, user)) if user.role == "student" else []
    result = recommend_path_for_course(course_id, graph, mastered)
    rate = round(100 * len(mastered) / max(1, len(graph.nodes)), 1)
    return execute(lambda: graph_lifecycle.enrich_learning_path(course_id, result, user, rate))


# Teaching classes and class-scoped learning
@app.get("/api/classrooms", response_model=list[Classroom])
def list_classrooms(user: Annotated[User, Depends(operational_user)]) -> list[Classroom]:
    return execute(lambda: platform.list_classrooms(user))


@app.post("/api/classrooms", response_model=Classroom, status_code=201)
def create_classroom(payload: ClassroomCreate, user: Annotated[User, Depends(operational_user)]) -> Classroom:
    return execute(lambda: platform.create_classroom(payload, user))


@app.get("/api/classrooms/{classroom_id}", response_model=Classroom)
def get_classroom(classroom_id: str, user: Annotated[User, Depends(operational_user)]) -> Classroom:
    return execute(lambda: platform.get_classroom(classroom_id, user))


@app.put("/api/classrooms/{classroom_id}", response_model=Classroom)
def update_classroom(
    classroom_id: str, payload: ClassroomUpdate, user: Annotated[User, Depends(operational_user)],
) -> Classroom:
    return execute(lambda: platform.update_classroom(classroom_id, payload, user))


@app.post("/api/classrooms/join", response_model=Classroom)
def join_class(payload: JoinClassRequest, user: Annotated[User, Depends(operational_user)]) -> Classroom:
    return execute(lambda: platform.join_class(payload.join_code, user))


@app.post("/api/classrooms/{classroom_id}/join-code/reset", response_model=Classroom)
def reset_join_code(classroom_id: str, user: Annotated[User, Depends(operational_user)]) -> Classroom:
    return execute(lambda: platform.reset_join_code(classroom_id, user))


@app.get("/api/classrooms/{classroom_id}/members", response_model=list[User])
def class_members(classroom_id: str, user: Annotated[User, Depends(operational_user)]) -> list[User]:
    return execute(lambda: platform.list_class_members(classroom_id, user))


@app.post("/api/classrooms/{classroom_id}/members", status_code=204)
def add_class_member(
    classroom_id: str, payload: EnrollmentCreate, user: Annotated[User, Depends(operational_user)],
) -> None:
    execute(lambda: platform.add_student_to_class(classroom_id, payload.student_id, user))


@app.post("/api/classrooms/{classroom_id}/teachers", status_code=204)
def assign_class_teacher(
    classroom_id: str, payload: ClassTeacherAssign, user: Annotated[User, Depends(operational_user)],
) -> None:
    execute(lambda: platform.assign_teacher(classroom_id, payload.teacher_id, payload.can_edit_course, user))


@app.put("/api/admin/classrooms/{classroom_id}/primary-teacher", response_model=Classroom)
def reassign_primary_teacher(
    classroom_id: str, payload: ClassPrimaryTeacherUpdate,
    user: Annotated[User, Depends(operational_user)],
) -> Classroom:
    return execute(lambda: platform.reassign_primary_teacher(classroom_id, payload.teacher_id, user))


@app.get("/api/classrooms/{classroom_id}/graph", response_model=KnowledgeGraph)
def class_graph(classroom_id: str, user: Annotated[User, Depends(operational_user)]) -> KnowledgeGraph:
    return execute(lambda: platform.get_class_graph(classroom_id, user))


@app.put("/api/classrooms/{classroom_id}/progress/{node_id}", response_model=KnowledgeNode)
def class_progress(
    classroom_id: str, node_id: str, payload: ProgressUpdate,
    user: Annotated[User, Depends(operational_user)],
) -> KnowledgeNode:
    return execute(lambda: platform.set_class_progress(classroom_id, node_id, payload.mastered, user))


@app.post("/api/classrooms/{classroom_id}/learning-path", response_model=LearningPathResult)
def class_learning_path(
    classroom_id: str, payload: LearningPathRequest, user: Annotated[User, Depends(operational_user)],
) -> LearningPathResult:
    graph = execute(lambda: platform.get_class_graph(classroom_id, user))
    mastered = payload.mastered_node_ids
    if mastered is None and user.role == "student":
        mastered = execute(lambda: platform.class_mastered_node_ids(classroom_id, user))
    mastered = mastered or []
    classroom = execute(lambda: platform.get_classroom(classroom_id, user))
    result = recommend_path_for_course(classroom.course_id, graph, mastered)
    rate = round(100 * len(mastered) / max(1, len(graph.nodes)), 1)
    return execute(lambda: graph_lifecycle.enrich_learning_path(classroom.course_id, result, user, rate))


@app.post("/api/classrooms/{classroom_id}/qa", response_model=QAResult)
def class_qa(classroom_id: str, payload: QARequest, user: Annotated[User, Depends(operational_user)]) -> QAResult:
    classroom = execute(lambda: platform.get_classroom(classroom_id, user))
    return execute(lambda: graph_lifecycle.graphrag_answer(classroom.course_id, payload.question, user))


@app.get("/api/classrooms/{classroom_id}/diagnosis", response_model=DiagnosisResult)
def class_diagnosis(classroom_id: str, user: Annotated[User, Depends(operational_user)]) -> DiagnosisResult:
    return execute(lambda: platform.diagnosis(classroom_id, user))


@app.post("/api/classrooms/{classroom_id}/exercises", response_model=list[ExerciseResult])
def class_exercises(
    classroom_id: str,
    user: Annotated[User, Depends(operational_user)],
    payload: ExerciseGenerateRequest | None = None,
) -> list[ExerciseResult]:
    return execute(lambda: platform.generate_exercises(classroom_id, user, payload or ExerciseGenerateRequest()))


# Feedback tickets
@app.get("/api/tickets", response_model=list[Ticket])
def list_tickets(user: Annotated[User, Depends(current_user)]) -> list[Ticket]:
    return execute(lambda: platform.list_tickets(user))


@app.post("/api/tickets", response_model=Ticket, status_code=201)
def create_ticket(payload: TicketCreate, user: Annotated[User, Depends(current_user)]) -> Ticket:
    return execute(lambda: platform.create_ticket(payload, user))


@app.get("/api/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: str, user: Annotated[User, Depends(current_user)]) -> Ticket:
    return execute(lambda: platform.get_ticket(ticket_id, user))


@app.post("/api/tickets/{ticket_id}/messages", response_model=Ticket)
def reply_ticket(
    ticket_id: str, payload: TicketReplyCreate, user: Annotated[User, Depends(current_user)],
) -> Ticket:
    return execute(lambda: platform.reply_ticket(ticket_id, payload, user))


@app.post("/api/tickets/{ticket_id}/attachments", response_model=Ticket)
async def add_ticket_attachment(
    ticket_id: str, file: UploadFile = File(...), user: User = Depends(current_user),
) -> Ticket:
    raw = await file.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="附件不能为空且不能超过 10 MB")
    return execute(lambda: platform.save_ticket_attachment(ticket_id, file.filename or "attachment", raw, user))


@app.get("/api/tickets/{ticket_id}/attachments/{attachment_id}")
def download_ticket_attachment(
    ticket_id: str, attachment_id: str, user: Annotated[User, Depends(current_user)],
) -> FileResponse:
    path, filename = execute(lambda: platform.ticket_attachment_path(ticket_id, attachment_id, user))
    return FileResponse(path, filename=filename)


@app.get("/api/notifications")
def notifications(user: Annotated[User, Depends(current_user)]) -> list[dict]:
    return platform.list_notifications(user)


@app.put("/api/notifications/{notification_id}/read", status_code=204)
def read_notification(notification_id: str, user: Annotated[User, Depends(current_user)]) -> None:
    execute(lambda: platform.mark_notification_read(notification_id, user))


@app.get("/api/files/avatars/{filename}")
def avatar_file(filename: str, user: Annotated[User, Depends(current_user)]) -> FileResponse:
    path = (storage.UPLOAD_DIR / "avatars" / filename).resolve()
    root = (storage.UPLOAD_DIR / "avatars").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(path)


@app.get("/api/integrations")
def integrations(user: Annotated[User, Depends(operational_user)]) -> dict:
    from app.services.neo4j_adapter import status as neo4j_status
    return {"aigc": {"mode": deepseek.extraction_mode()}, "neo4j": neo4j_status()}


@app.post("/api/courses/{course_id}/graph/sync")
def sync_course_graph(course_id: str, user: Annotated[User, Depends(operational_user)]) -> dict:
    return execute(lambda: graph_lifecycle.sync_neo4j(course_id, user))


@app.post("/api/admin/integrations/neo4j/sync")
def sync_all_course_graphs(user: Annotated[User, Depends(operational_user)]) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以执行全校图谱同步")
    from app.services.neo4j_adapter import sync_all_confirmed_graphs
    return sync_all_confirmed_graphs()


@app.put("/api/admin/tickets/{ticket_id}", response_model=Ticket)
def admin_update_ticket(
    ticket_id: str, payload: TicketUpdate, user: Annotated[User, Depends(operational_user)],
) -> Ticket:
    return execute(lambda: platform.update_ticket(ticket_id, payload, user))


# Independent administrator APIs
@app.get("/api/admin/dashboard", response_model=DashboardStats)
def admin_dashboard(user: Annotated[User, Depends(operational_user)]) -> DashboardStats:
    return execute(lambda: platform.admin_dashboard(user))


@app.get("/api/admin/users", response_model=list[User])
def admin_users(
    role: str = "", status: str = "", query: str = "", user: User = Depends(operational_user),
) -> list[User]:
    return execute(lambda: platform.admin_list_users(user, role, status, query))


@app.put("/api/admin/users/{user_id}", response_model=User)
def admin_update_user(
    user_id: str, payload: AdminUserUpdate, user: Annotated[User, Depends(operational_user)],
) -> User:
    return execute(lambda: platform.admin_update_user(user_id, payload, user))


@app.post("/api/admin/teachers/{teacher_id}/review", response_model=User)
def admin_review_teacher(
    teacher_id: str, payload: TeacherReview, user: Annotated[User, Depends(operational_user)],
) -> User:
    return execute(lambda: platform.review_teacher(teacher_id, payload, user))


@app.post("/api/classrooms/{classroom_id}/imports/preview", response_model=ImportPreview)
async def preview_import(
    classroom_id: str, file: UploadFile = File(...), user: User = Depends(operational_user),
) -> ImportPreview:
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="导入文件为空")
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="导入文件不能超过 5 MB")
    return execute(lambda: platform.preview_student_import(classroom_id, file.filename or "students.csv", raw, user))


@app.post("/api/imports/{job_id}/commit", response_model=ImportCommitResult)
def commit_import(job_id: str, user: Annotated[User, Depends(operational_user)]) -> ImportCommitResult:
    return execute(lambda: platform.commit_student_import(job_id, user))


@app.get("/api/admin/audit-logs")
def audit_logs(limit: int = Query(100, ge=1, le=500), user: User = Depends(operational_user)) -> list[dict]:
    return execute(lambda: platform.list_audit_logs(user, limit))


@app.post("/api/admin/reset-demo")
def reset_demo(user: Annotated[User, Depends(operational_user)]) -> dict:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以重置演示数据")
    storage.reset_store()
    return {"status": "reset"}
