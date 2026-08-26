import type { Course, DocumentInfo, KnowledgeEdge, KnowledgeGraph, KnowledgeNode, LearningPathResult, QAResult, User } from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (username: string, role: User['role']) =>
    request<{ token: string; user: User }>('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: 'demo', role }),
    }),
  listCourses: () => request<Course[]>('/api/courses'),
  createCourse: (course: Pick<Course, 'name' | 'description' | 'status'>) =>
    request<Course>('/api/courses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(course),
    }),
  updateCourse: (course: Pick<Course, 'id' | 'name' | 'description' | 'status'>) =>
    request<Course>(`/api/courses/${course.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: course.name, description: course.description, status: course.status }),
    }),
  deleteCourse: (courseId: string) => request(`/api/courses/${courseId}`, { method: 'DELETE' }),
  getGraph: (courseId: string) => request<KnowledgeGraph>(`/api/courses/${courseId}/graph`),
  listDocuments: (courseId: string) => request<DocumentInfo[]>(`/api/courses/${courseId}/documents`),
  deleteDocument: (courseId: string, documentId: string) => request(`/api/courses/${courseId}/documents/${documentId}`, { method: 'DELETE' }),
  uploadDocument: (courseId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return request(`/api/courses/${courseId}/documents`, { method: 'POST', body: formData });
  },
  extract: (courseId: string) => request<{ message: string; graph: KnowledgeGraph }>(`/api/courses/${courseId}/extract`, { method: 'POST' }),
  addNode: (courseId: string, node: Omit<KnowledgeNode, 'id'>) =>
    request<KnowledgeNode>(`/api/courses/${courseId}/graph/nodes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(node),
    }),
  updateNode: (courseId: string, node: KnowledgeNode) =>
    request<KnowledgeNode>(`/api/courses/${courseId}/graph/nodes/${node.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: node.name,
        type: node.type,
        definition: node.definition,
        example: node.example,
        resources: node.resources,
        mastered: node.mastered,
      }),
    }),
  deleteNode: (courseId: string, nodeId: string) => request(`/api/courses/${courseId}/graph/nodes/${nodeId}`, { method: 'DELETE' }),
  addEdge: (courseId: string, edge: Omit<KnowledgeEdge, 'id'>) =>
    request<KnowledgeEdge>(`/api/courses/${courseId}/graph/edges`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(edge),
    }),
  updateEdge: (courseId: string, edge: KnowledgeEdge) =>
    request<KnowledgeEdge>(`/api/courses/${courseId}/graph/edges/${edge.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: edge.source, target: edge.target, relation: edge.relation, label: edge.label }),
    }),
  deleteEdge: (courseId: string, edgeId: string) => request(`/api/courses/${courseId}/graph/edges/${edgeId}`, { method: 'DELETE' }),
  qa: (courseId: string, question: string) =>
    request<QAResult>(`/api/courses/${courseId}/qa`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
  learningPath: (courseId: string, masteredNodeIds: string[]) =>
    request<LearningPathResult>(`/api/courses/${courseId}/learning-path`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mastered_node_ids: masteredNodeIds }),
    }),
};
