export type RelationType = 'contains' | 'prerequisite' | 'related';
export type AccountStatus = 'pending' | 'active' | 'rejected' | 'disabled';

export interface GraphStats { nodes: number; edges: number; relation_types: number }

export interface User {
  id: string;
  username: string;
  name: string;
  role: 'admin' | 'teacher' | 'student';
  organization: string;
  email: string;
  phone: string;
  avatar_url: string;
  account_status: AccountStatus;
  must_change_password: boolean;
  student_no: string;
  department: string;
  title: string;
  rejection_reason: string;
}

export interface AuthResult { token: string; user: User; expires_at: string }

export interface Course {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'published' | 'archived';
  owner_id: string;
  owner_name: string;
  document_count: number;
  stats: GraphStats;
  classroom_count: number;
  student_count: number;
  source_incomplete: boolean;
}

export interface Classroom {
  id: string;
  course_id: string;
  course_name: string;
  name: string;
  semester: string;
  join_code: string;
  join_enabled: boolean;
  status: 'draft' | 'active' | 'closed';
  primary_teacher_id: string;
  primary_teacher_name: string;
  teacher_count: number;
  student_count: number;
  active_student_count: number;
  average_progress: number;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  format: string;
  size: number;
  parsed_chars: number;
  created_at: string;
  status: string;
  source_node_count: number;
}

export interface DocumentImpact {
  document_id: string;
  removable_nodes: number;
  removable_edges: number;
  preserved_manual_nodes: number;
  shared_nodes: number;
}

export interface KnowledgeNode {
  id: string;
  name: string;
  type: string;
  definition: string;
  example: string;
  resources: string[];
  mastered: boolean;
  source_refs?: SourceReference[];
}

export interface SourceReference {
  document_id: string;
  filename: string;
  source_type?: string;
  page_no?: number;
  excerpt: string;
  confidence: number;
  reason: string;
}

export interface KnowledgeEdge {
  id: string;
  source: string;
  target: string;
  relation: RelationType;
  label: string;
  source_refs?: SourceReference[];
}

export interface AIStatus {
  provider: string;
  configured: boolean;
  model: string;
  mode: 'deepseek' | 'offline';
  capabilities: string[];
}

export interface KnowledgeGraph { nodes: KnowledgeNode[]; edges: KnowledgeEdge[] }

export interface ExtractionJob {
  id: string;
  course_id: string;
  status: 'queued' | 'parsing' | 'extracting' | 'merging' | 'review' | 'completed' | 'failed';
  progress: number;
  mode: 'deepseek' | 'mock';
  message: string;
  candidate_version_id: string;
  created_at: string;
  updated_at: string;
}

export interface GraphVersion {
  id: string;
  course_id: string;
  version_no: number;
  status: 'candidate' | 'active' | 'rejected' | 'superseded';
  trigger: string;
  summary: string;
  created_at: string;
  created_by: string;
  graph?: KnowledgeGraph;
}

export interface GraphQuality {
  score: number;
  duplicate_rate: number;
  isolated_rate: number;
  relation_coverage: number;
  source_coverage: number;
  notes: string[];
}

export interface QAResult {
  answer: string;
  citations: KnowledgeNode[];
  confidence: string;
  evidence: Evidence[];
  mode: string;
}

export interface Evidence {
  id?: string;
  source: string;
  excerpt: string;
  type: string;
  document_id?: string;
  page_no?: number;
  bm25_score?: number;
  rank?: number;
}

export interface LearningPathItem { node: KnowledgeNode; priority: number; reason: string }
export interface LearningPathResult {
  recommendations: LearningPathItem[];
  path_edges: KnowledgeEdge[];
  ai_summary: string;
  mode: string;
  evidence: Evidence[];
}

export interface DiagnosisResult {
  mastery_rate: number;
  mastered_count: number;
  total_count: number;
  weak_nodes: KnowledgeNode[];
  suggestions: string[];
  ai_analysis: string;
  mode: string;
  evidence: Evidence[];
}

export interface ExerciseResult {
  node_id: string;
  node_name: string;
  question: string;
  answer: string;
  explanation: string;
  question_type: string;
  difficulty: string;
  sources: Evidence[];
  mode: string;
}

export interface TicketMessage { id: string; content: string; created_at: string; author_id: string; author_name: string; author_role: string }
export interface Ticket {
  id: string;
  creator_id: string;
  creator_name: string;
  category: string;
  severity: string;
  subject: string;
  description: string;
  status: string;
  assigned_admin_id: string;
  assigned_admin_name: string;
  created_at: string;
  updated_at: string;
  messages: TicketMessage[];
  attachments: Array<{ id: string; filename: string; size: number; created_at: string; url: string }>;
}

export interface DashboardStats {
  users: number;
  teachers: number;
  students: number;
  pending_teachers: number;
  courses: number;
  classrooms: number;
  open_tickets: number;
}

export interface ImportPreview {
  job_id: string;
  total: number;
  valid: number;
  invalid: number;
  rows: Array<Record<string, unknown>>;
}

export interface ImportCommitResult {
  created: number;
  updated: number;
  enrolled: number;
  credentials: Array<{ student_no: string; name: string; temporary_password: string }>;
}
