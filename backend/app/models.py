from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RelationType = Literal["contains", "prerequisite", "related"]


class GraphStats(BaseModel):
    nodes: int = 0
    edges: int = 0
    relation_types: int = 0


class Course(BaseModel):
    id: str
    name: str
    description: str
    document_count: int = 0
    stats: GraphStats = Field(default_factory=GraphStats)


class CourseCreate(BaseModel):
    name: str
    description: str = ""


class DocumentInfo(BaseModel):
    id: str
    filename: str
    format: str
    size: int
    parsed_chars: int


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
    mastered_node_ids: list[str] = Field(default_factory=list)


class LearningPathItem(BaseModel):
    node: KnowledgeNode
    priority: int
    reason: str


class LearningPathResult(BaseModel):
    recommendations: list[LearningPathItem]
    path_edges: list[KnowledgeEdge]
