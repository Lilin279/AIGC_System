export type RelationType = 'contains' | 'prerequisite' | 'related';

export interface GraphStats {
  nodes: number;
  edges: number;
  relation_types: number;
}

export interface Course {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'published' | 'archived';
  owner_id: string;
  owner_name: string;
  document_count: number;
  stats: GraphStats;
}

export interface User {
  id: string;
  name: string;
  role: 'admin' | 'teacher' | 'student';
  organization: string;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  format: string;
  size: number;
  parsed_chars: number;
  created_at: string;
}

export interface AuthResult {
  token: string;
  user: User;
  expires_at: string;
}

export interface KnowledgeNode {
  id: string;
  name: string;
  type: string;
  definition: string;
  example: string;
  resources: string[];
  mastered: boolean;
}

export interface KnowledgeEdge {
  id: string;
  source: string;
  target: string;
  relation: RelationType;
  label: string;
}

export interface KnowledgeGraph {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

export interface QAResult {
  answer: string;
  citations: KnowledgeNode[];
  confidence: string;
}

export interface LearningPathItem {
  node: KnowledgeNode;
  priority: number;
  reason: string;
}

export interface LearningPathResult {
  recommendations: LearningPathItem[];
  path_edges: KnowledgeEdge[];
}
