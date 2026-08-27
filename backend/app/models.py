from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RelationType = Literal["contains", "prerequisite", "related"]


class GraphStats(BaseModel):
    nodes: int = 0
    edges: int = 0
    relation_types: int = 0


class User(BaseModel):
    id: str
    name: str
    role: Literal["admin", "teacher", "student"]
    organization: str = "演示学校"


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str
    organization: str = "金扬智能示范学校"


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


class KnowledgeNode(BaseModel):
    id: str
    name: str
    type: str = "concept"
    definition: str = ""
    example: str = ""
    resources: list[str] = Field(default_factory=list)
    mastered: bool = False


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
