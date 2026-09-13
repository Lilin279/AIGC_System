import type {
  AIStatus, AuthResult, Classroom, Course, DashboardStats, DiagnosisResult, DocumentImpact, DocumentInfo,
  ExerciseResult, ExtractionJob, GraphQuality, GraphVersion, ImportCommitResult, ImportPreview, IntegrationStatus,
  KnowledgeEdge, KnowledgeGraph, KnowledgeNode, LearningPathResult, QAResult, Ticket, User,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
const TOKEN_KEY = 'coursegraph_access_token';
let accessToken = localStorage.getItem(TOKEN_KEY) ?? '';

export function setAccessToken(token: string) {
  accessToken = token;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function hasAccessToken() { return Boolean(accessToken) }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => undefined) as { detail?: string } | undefined;
    if (response.status === 401) {
      setAccessToken('');
      window.dispatchEvent(new Event('coursegraph:unauthorized'));
    }
    throw new Error(payload?.detail || `请求失败（${response.status}）`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  aiStatus: () => request<AIStatus>('/api/ai/status'),
  integrations: () => request<IntegrationStatus>('/api/integrations'),
  login: (username: string, password: string) => request<AuthResult>('/api/auth/login', json('POST', { username, password })),
  registerStudent: (payload: object) => request<AuthResult>('/api/auth/register', json('POST', payload)),
  registerTeacher: (payload: object) => request<AuthResult>('/api/auth/register/teacher', json('POST', payload)),
  me: () => request<User>('/api/auth/me'),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  updateProfile: (payload: object) => request<User>('/api/profile', json('PUT', payload)),
  updatePassword: (current_password: string, new_password: string) => request<void>('/api/profile/password', json('PUT', { current_password, new_password })),
  uploadAvatar: (file: File) => { const data = new FormData(); data.append('file', file); return request<User>('/api/profile/avatar', { method: 'POST', body: data }); },

  listCourses: () => request<Course[]>('/api/courses'),
  createCourse: (course: object) => request<Course>('/api/courses', json('POST', course)),
  updateCourse: (courseId: string, course: object) => request<Course>(`/api/courses/${courseId}`, json('PUT', course)),
  deleteCourse: (courseId: string) => request(`/api/courses/${courseId}`, { method: 'DELETE' }),
  getGraph: (courseId: string) => request<KnowledgeGraph>(`/api/courses/${courseId}/graph`),
  listDocuments: (courseId: string) => request<DocumentInfo[]>(`/api/courses/${courseId}/documents`),
  documentImpact: (courseId: string, documentId: string) => request<DocumentImpact>(`/api/courses/${courseId}/documents/${documentId}/impact`),
  deleteDocument: (courseId: string, documentId: string, rollbackGraph: boolean) =>
    request<{ deleted: string; rollback_graph: boolean; needs_reextract: boolean }>(`/api/courses/${courseId}/documents/${documentId}?rollback_graph=${rollbackGraph}`, { method: 'DELETE' }),
  uploadDocument: (courseId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request<DocumentInfo>(`/api/courses/${courseId}/documents`, { method: 'POST', body: formData });
  },
  extract: (courseId: string) => request<ExtractionJob>(`/api/courses/${courseId}/extract`, { method: 'POST' }),
  extractionJob: (jobId: string) => request<ExtractionJob>(`/api/extraction-jobs/${jobId}`),
  extractionJobs: (courseId: string) => request<ExtractionJob[]>(`/api/courses/${courseId}/extraction-jobs`),
  graphVersions: (courseId: string) => request<GraphVersion[]>(`/api/courses/${courseId}/graph/versions`),
  graphVersion: (courseId: string, versionId: string) => request<GraphVersion>(`/api/courses/${courseId}/graph/versions/${versionId}`),
  acceptVersion: (courseId: string, versionId: string) => request<GraphVersion>(`/api/courses/${courseId}/graph/versions/${versionId}/accept`, { method: 'POST' }),
  rejectVersion: (courseId: string, versionId: string) => request<GraphVersion>(`/api/courses/${courseId}/graph/versions/${versionId}/reject`, { method: 'POST' }),
  restoreVersion: (courseId: string, versionId: string) => request<GraphVersion>(`/api/courses/${courseId}/graph/versions/${versionId}/restore`, { method: 'POST' }),
  graphQuality: (courseId: string) => request<GraphQuality>(`/api/courses/${courseId}/graph/quality`),
  syncNeo4j: (courseId: string) => request<{ synced: boolean; message: string }>(`/api/courses/${courseId}/graph/sync`, { method: 'POST' }),
  addNode: (courseId: string, node: object) => request<KnowledgeNode>(`/api/courses/${courseId}/graph/nodes`, json('POST', node)),
  updateNode: (courseId: string, node: KnowledgeNode) => request<KnowledgeNode>(`/api/courses/${courseId}/graph/nodes/${node.id}`, json('PUT', node)),
  deleteNode: (courseId: string, nodeId: string) => request(`/api/courses/${courseId}/graph/nodes/${nodeId}`, { method: 'DELETE' }),
  addEdge: (courseId: string, edge: object) => request<KnowledgeEdge>(`/api/courses/${courseId}/graph/edges`, json('POST', edge)),
  updateEdge: (courseId: string, edge: KnowledgeEdge) => request<KnowledgeEdge>(`/api/courses/${courseId}/graph/edges/${edge.id}`, json('PUT', edge)),
  deleteEdge: (courseId: string, edgeId: string) => request(`/api/courses/${courseId}/graph/edges/${edgeId}`, { method: 'DELETE' }),
  qa: (courseId: string, question: string) => request<QAResult>(`/api/courses/${courseId}/qa`, json('POST', { question })),
  learningPath: (courseId: string) => request<LearningPathResult>(`/api/courses/${courseId}/learning-path`, json('POST', {})),

  listClassrooms: () => request<Classroom[]>('/api/classrooms'),
  createClassroom: (payload: object) => request<Classroom>('/api/classrooms', json('POST', payload)),
  updateClassroom: (classroomId: string, payload: object) => request<Classroom>(`/api/classrooms/${classroomId}`, json('PUT', payload)),
  joinClass: (join_code: string) => request<Classroom>('/api/classrooms/join', json('POST', { join_code })),
  resetJoinCode: (classroomId: string) => request<Classroom>(`/api/classrooms/${classroomId}/join-code/reset`, { method: 'POST' }),
  classMembers: (classroomId: string) => request<User[]>(`/api/classrooms/${classroomId}/members`),
  classGraph: (classroomId: string) => request<KnowledgeGraph>(`/api/classrooms/${classroomId}/graph`),
  classProgress: (classroomId: string, nodeId: string, mastered: boolean) => request<KnowledgeNode>(`/api/classrooms/${classroomId}/progress/${nodeId}`, json('PUT', { mastered })),
  classQa: (classroomId: string, question: string) => request<QAResult>(`/api/classrooms/${classroomId}/qa`, json('POST', { question })),
  classPath: (classroomId: string) => request<LearningPathResult>(`/api/classrooms/${classroomId}/learning-path`, json('POST', {})),
  diagnosis: (classroomId: string) => request<DiagnosisResult>(`/api/classrooms/${classroomId}/diagnosis`),
  exercises: (classroomId: string) => request<ExerciseResult[]>(`/api/classrooms/${classroomId}/exercises`, { method: 'POST' }),
  previewImport: (classroomId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request<ImportPreview>(`/api/classrooms/${classroomId}/imports/preview`, { method: 'POST', body: formData });
  },
  commitImport: (jobId: string) => request<ImportCommitResult>(`/api/imports/${jobId}/commit`, { method: 'POST' }),

  tickets: () => request<Ticket[]>('/api/tickets'),
  createTicket: (payload: object) => request<Ticket>('/api/tickets', json('POST', payload)),
  ticket: (ticketId: string) => request<Ticket>(`/api/tickets/${ticketId}`),
  replyTicket: (ticketId: string, content: string) => request<Ticket>(`/api/tickets/${ticketId}/messages`, json('POST', { content })),
  addTicketAttachment: (ticketId: string, file: File) => { const data = new FormData(); data.append('file', file); return request<Ticket>(`/api/tickets/${ticketId}/attachments`, { method: 'POST', body: data }); },
  updateTicket: (ticketId: string, payload: object) => request<Ticket>(`/api/admin/tickets/${ticketId}`, json('PUT', payload)),

  dashboard: () => request<DashboardStats>('/api/admin/dashboard'),
  adminUsers: (role = '', status = '', query = '') => request<User[]>(`/api/admin/users?role=${role}&status=${status}&query=${encodeURIComponent(query)}`),
  reviewTeacher: (teacherId: string, action: 'approve' | 'reject', reason = '') => request<User>(`/api/admin/teachers/${teacherId}/review`, json('POST', { action, reason })),
  adminUpdateUser: (userId: string, payload: object) => request<User>(`/api/admin/users/${userId}`, json('PUT', payload)),
  reassignPrimaryTeacher: (classroomId: string, teacher_id: string) => request<Classroom>(`/api/admin/classrooms/${classroomId}/primary-teacher`, json('PUT', { teacher_id })),
  auditLogs: () => request<Array<Record<string, string>>>('/api/admin/audit-logs'),
};
