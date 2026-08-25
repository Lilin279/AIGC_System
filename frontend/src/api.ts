import type { Course, KnowledgeGraph, KnowledgeNode, LearningPathResult, QAResult } from './types';

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
  listCourses: () => request<Course[]>('/api/courses'),
  getGraph: (courseId: string) => request<KnowledgeGraph>(`/api/courses/${courseId}/graph`),
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
