from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RelationType = Literal["contains", "prerequisite", "related"]


class SourceReference(BaseModel):
    document_id: str = ""
    filename: str = ""
    source_type: str = "aigc"
    page_no: int | None = None
    excerpt: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class GraphStats(BaseModel):
    nodes: int = 0
    edges: int = 0
    relation_types: int = 0


class User(BaseModel):
    id: str
    name: str
    role: Literal["admin", "teacher", "student"]
    organization: str = ""
    username: str = ""
    email: str = ""
    phone: str = ""
    avatar_url: str = ""
    account_status: Literal["pending", "active", "rejected", "disabled"] = "active"
    must_change_password: bool = False
    student_no: str = ""
    department: str = ""
    title: str = ""
    rejection_reason: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str
    organization: str = ""


class TeacherRegisterRequest(RegisterRequest):
    email: str = ""
    phone: str = ""
    department: str = ""
    title: str = ""


class ProfileUpdate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    title: str = ""


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str


class LoginResult(BaseModel):
    token: str
    user: User
    expires_at: str


class Course(BaseModel):
    id: str
    name: str
    description: str
    status: Literal["draft", "published", "archived"] = "draft"
    owner_id: str = ""
    owner_name: str = ""
    document_count: int = 0
    stats: GraphStats = Field(default_factory=GraphStats)
    classroom_count: int = 0
    student_count: int = 0
    source_incomplete: bool = False


class CourseCreate(BaseModel):
    name: str
    description: str = ""
    status: Literal["draft", "published", "archived"] = "draft"


class CourseUpdate(BaseModel):
    name: str
    description: str = ""
    status: Literal["draft", "published", "archived"] = "draft"


class DocumentInfo(BaseModel):
    id: str
    filename: str
    format: str
    size: int
    parsed_chars: int
    created_at: str = ""
    status: str = "active"
    source_node_count: int = 0


class DocumentDeleteRequest(BaseModel):
    rollback_graph: bool = True


class DocumentImpact(BaseModel):
    document_id: str
    removable_nodes: int = 0
    removable_edges: int = 0
    preserved_manual_nodes: int = 0
    shared_nodes: int = 0


class KnowledgeNode(BaseModel):
    id: str
    name: str
    type: str = "concept"
    definition: str = ""
    example: str = ""
    resources: list[str] = Field(default_factory=list)
    mastered: bool = False
    source_refs: list[SourceReference] = Field(default_factory=list)


class KnowledgeNodeCreate(BaseModel):
    name: str
    type: str = "concept"
    definition: str = ""
    example: str = ""
    resources: list[str] = Field(default_factory=list)
    mastered: bool = False


class KnowledgeEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: RelationType
    label: str
    source_refs: list[SourceReference] = Field(default_factory=list)


class KnowledgeEdgeCreate(BaseModel):
    source: str
    target: str
    relation: RelationType
    label: str = ""


class KnowledgeEdgeUpdate(BaseModel):
    source: str
    target: str
    relation: RelationType
    label: str = ""


class KnowledgeGraph(BaseModel):
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)


class GraphVersion(BaseModel):
    id: str
    course_id: str
    version_no: int
    status: Literal["candidate", "active", "rejected", "superseded"]
    trigger: str
    summary: str = ""
    created_at: str = ""
    created_by: str = ""
    graph: KnowledgeGraph | None = None


class ExtractionJob(BaseModel):
    id: str
    course_id: str
    status: Literal["queued", "parsing", "extracting", "merging", "review", "completed", "failed"]
    progress: int = 0
    mode: Literal["deepseek", "mock"] = "mock"
    message: str = ""
    candidate_version_id: str = ""
    created_at: str = ""
    updated_at: str = ""


class GraphQuality(BaseModel):
    score: int
    duplicate_rate: float
    isolated_rate: float
    relation_coverage: float
    source_coverage: float
    notes: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    course_id: str
    status: str
    message: str
    graph: KnowledgeGraph


class QARequest(BaseModel):
    question: str


class QAResult(BaseModel):
    answer: str
    citations: list[KnowledgeNode] = Field(default_factory=list)
    confidence: str = "demo"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = "offline"


ExerciseQuestionType = Literal["基础题", "应用题", "易错题"]


class ExerciseGenerateRequest(BaseModel):
    question_types: list[ExerciseQuestionType] = Field(
        default_factory=lambda: ["基础题", "应用题", "易错题"], min_length=1, max_length=3,
    )
    count: int = Field(default=3, ge=1, le=10)


class AIStatus(BaseModel):
    provider: str = "deepseek"
    configured: bool = False
    model: str = "deepseek-v4-flash"
    mode: Literal["deepseek", "offline"] = "offline"
    capabilities: list[str] = Field(default_factory=list)


class LearningPathRequest(BaseModel):
    mastered_node_ids: list[str] | None = None


class ProgressUpdate(BaseModel):
    mastered: bool


class LearningPathItem(BaseModel):
    node: KnowledgeNode
    priority: int
    reason: str


class LearningPathResult(BaseModel):
    recommendations: list[LearningPathItem]
    path_edges: list[KnowledgeEdge]
    ai_summary: str = ""
    mode: str = "offline-rule"
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class Classroom(BaseModel):
    id: str
    course_id: str
    course_name: str = ""
    name: str
    semester: str = ""
    join_code: str
    join_enabled: bool = True
    status: Literal["draft", "active", "closed"] = "active"
    primary_teacher_id: str
    primary_teacher_name: str = ""
    teacher_count: int = 1
    student_count: int = 0
    active_student_count: int = 0
    average_progress: float = 0


class ClassroomCreate(BaseModel):
    course_id: str
    name: str
    semester: str = ""
    status: Literal["draft", "active", "closed"] = "active"


class ClassroomUpdate(BaseModel):
    name: str
    semester: str = ""
    join_enabled: bool = True
    status: Literal["draft", "active", "closed"] = "active"


class JoinClassRequest(BaseModel):
    join_code: str


class ClassTeacherAssign(BaseModel):
    teacher_id: str
    can_edit_course: bool = False


class ClassPrimaryTeacherUpdate(BaseModel):
    teacher_id: str


class EnrollmentCreate(BaseModel):
    student_id: str


class TeacherReview(BaseModel):
    action: Literal["approve", "reject"]
    reason: str = ""


class AdminUserUpdate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    account_status: Literal["pending", "active", "rejected", "disabled"]
    department: str = ""
    title: str = ""
    student_no: str = ""


class DashboardStats(BaseModel):
    users: int = 0
    teachers: int = 0
    students: int = 0
    pending_teachers: int = 0
    courses: int = 0
    classrooms: int = 0
    open_tickets: int = 0


class ImportPreview(BaseModel):
    job_id: str
    total: int
    valid: int
    invalid: int
    rows: list[dict[str, Any]]


class ImportCommitResult(BaseModel):
    created: int
    updated: int
    enrolled: int
    credentials: list[dict[str, str]]


class TicketCreate(BaseModel):
    category: Literal["system", "course", "graph", "account", "other"] = "system"
    severity: Literal["low", "medium", "high", "urgent"] = "medium"
    subject: str
    description: str


class TicketReplyCreate(BaseModel):
    content: str


class TicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "waiting_user", "resolved", "closed"]
    assigned_admin_id: str = ""


class Ticket(BaseModel):
    id: str
    creator_id: str
    creator_name: str = ""
    category: str
    severity: str
    subject: str
    description: str
    status: str
    assigned_admin_id: str = ""
    assigned_admin_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class DiagnosisResult(BaseModel):
    mastery_rate: float
    mastered_count: int
    total_count: int
    weak_nodes: list[KnowledgeNode]
    suggestions: list[str]
    ai_analysis: str = ""
    mode: str = "offline-rule"
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class ExerciseResult(BaseModel):
    node_id: str
    node_name: str
    question: str
    answer: str
    explanation: str
    question_type: str = "基础题"
    difficulty: str = "基础"
    sources: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = "offline-rule"
