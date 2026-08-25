import { useCallback, useEffect, useMemo, useState } from 'react';
import { Bot, BookOpen, CheckCircle2, FileUp, GraduationCap, Network, PenLine, Route, Send, Sparkles } from 'lucide-react';
import { api } from './api';
import GraphView from './components/GraphView';
import type { Course, KnowledgeGraph, KnowledgeNode, LearningPathResult, QAResult } from './types';

const emptyGraph: KnowledgeGraph = { nodes: [], edges: [] };

export default function App() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState('');
  const [graph, setGraph] = useState<KnowledgeGraph>(emptyGraph);
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | undefined>();
  const [role, setRole] = useState<'teacher' | 'student'>('teacher');
  const [status, setStatus] = useState('正在连接后端服务...');
  const [question, setQuestion] = useState('函数和参数传递有什么关系？');
  const [qaResult, setQaResult] = useState<QAResult | undefined>();
  const [pathResult, setPathResult] = useState<LearningPathResult | undefined>();
  const [pathEdgeIds, setPathEdgeIds] = useState<string[]>([]);

  const selectedCourse = courses.find((course) => course.id === courseId);
  const masteredIds = useMemo(() => graph.nodes.filter((node) => node.mastered).map((node) => node.id), [graph.nodes]);

  const refreshCourses = useCallback(async () => {
    const data = await api.listCourses();
    setCourses(data);
    setCourseId((current) => current || data[0]?.id || '');
  }, []);

  const refreshGraph = useCallback(async (id: string) => {
    if (!id) return;
    const data = await api.getGraph(id);
    setGraph(data);
    setSelectedNode(data.nodes[0]);
  }, []);

  useEffect(() => {
    refreshCourses()
      .then(() => setStatus('系统就绪：已加载示例课程，可直接演示。'))
      .catch((error) => setStatus(`后端未连接：${error.message}`));
  }, [refreshCourses]);

  useEffect(() => {
    if (!courseId) return;
    refreshGraph(courseId).catch((error) => setStatus(`图谱加载失败：${error.message}`));
  }, [courseId, refreshGraph]);

  const uploadDocument = async (file?: File) => {
    if (!courseId || !file) return;
    setStatus('正在上传并解析课程资料...');
    await api.uploadDocument(courseId, file);
    setStatus('资料已解析，正在模拟 AIGC 知识抽取...');
    const result = await api.extract(courseId);
    setGraph(result.graph);
    setStatus(result.message);
    await refreshCourses();
  };

  const addDemoNode = async () => {
    if (!courseId) return;
    const node = await api.addNode(courseId, {
      name: '教师补充知识点',
      type: 'teacher-edit',
      definition: '教师可在自动抽取后补充、修正或删除图谱节点。',
      example: '例如补充课程里的重点公式、实验步骤或易错概念。',
      resources: ['教师手动修正记录'],
      mastered: false,
    });
    await refreshGraph(courseId);
    setSelectedNode(node);
    setStatus('已新增教师补充知识点。');
  };

  const toggleMastered = async (node: KnowledgeNode) => {
    if (!courseId) return;
    const updated = { ...node, mastered: !node.mastered };
    await api.updateNode(courseId, updated);
    await refreshGraph(courseId);
    setSelectedNode(updated);
  };

  const ask = async () => {
    if (!courseId || !question.trim()) return;
    setStatus('正在基于课程图谱生成离线 RAG 演示回答...');
    const result = await api.qa(courseId, question);
    setQaResult(result);
    setStatus('问答完成，结果已附带引用知识点。');
  };

  const recommend = async () => {
    if (!courseId) return;
    const result = await api.learningPath(courseId, masteredIds);
    setPathResult(result);
    setPathEdgeIds(result.path_edges.map((edge) => edge.id));
    setStatus('已根据前置关系生成下一步学习路径。');
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">服务外包竞赛原型</p>
          <h1>AIGC 课程知识图谱学习导航系统</h1>
        </div>
        <label className="course-picker">
          <BookOpen size={18} />
          <select value={courseId} onChange={(event) => setCourseId(event.target.value)}>
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      <section className="workspace">
        <aside className="sidebar">
          <button className={role === 'teacher' ? 'nav active' : 'nav'} onClick={() => setRole('teacher')}>
            <PenLine size={18} /> 教师端
          </button>
          <button className={role === 'student' ? 'nav active' : 'nav'} onClick={() => setRole('student')}>
            <GraduationCap size={18} /> 学生端
          </button>
          <div className="metric-panel">
            <span>知识点</span>
            <strong>{graph.nodes.length}</strong>
            <span>关系</span>
            <strong>{graph.edges.length}</strong>
            <span>已掌握</span>
            <strong>{masteredIds.length}</strong>
          </div>
          <p className="status">{status}</p>
        </aside>

        <section className="graph-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">当前课程</p>
              <h2>{selectedCourse?.name ?? '未选择课程'}</h2>
            </div>
            <span>{selectedCourse?.description}</span>
          </div>
          <GraphView graph={graph} selectedNodeId={selectedNode?.id} pathEdgeIds={pathEdgeIds} onSelectNode={setSelectedNode} />
        </section>

        <aside className="detail-panel">
          {role === 'teacher' ? (
            <TeacherPanel selectedNode={selectedNode} uploadDocument={uploadDocument} addDemoNode={addDemoNode} />
          ) : (
            <StudentPanel
              selectedNode={selectedNode}
              toggleMastered={toggleMastered}
              question={question}
              setQuestion={setQuestion}
              ask={ask}
              qaResult={qaResult}
              recommend={recommend}
              pathResult={pathResult}
            />
          )}
        </aside>
      </section>
    </main>
  );
}

function TeacherPanel({
  selectedNode,
  uploadDocument,
  addDemoNode,
}: {
  selectedNode?: KnowledgeNode;
  uploadDocument: (file?: File) => Promise<void>;
  addDemoNode: () => Promise<void>;
}) {
  return (
    <div className="panel-stack">
      <section className="tool-section">
        <h3><FileUp size={18} /> 资料上传与抽取</h3>
        <input type="file" accept=".txt,.md,.markdown" onChange={(event) => uploadDocument(event.target.files?.[0])} />
        <p>支持 TXT / Markdown，上传后自动进入 Mock AIGC 抽取流程。</p>
      </section>
      <section className="tool-section">
        <h3><Network size={18} /> 图谱修正</h3>
        <button className="primary" onClick={addDemoNode}><Sparkles size={16} /> 新增演示节点</button>
        {selectedNode && (
          <div className="node-detail">
            <b>{selectedNode.name}</b>
            <span>{selectedNode.definition}</span>
            <small>{selectedNode.example}</small>
          </div>
        )}
      </section>
    </div>
  );
}

function StudentPanel({
  selectedNode,
  toggleMastered,
  question,
  setQuestion,
  ask,
  qaResult,
  recommend,
  pathResult,
}: {
  selectedNode?: KnowledgeNode;
  toggleMastered: (node: KnowledgeNode) => Promise<void>;
  question: string;
  setQuestion: (value: string) => void;
  ask: () => Promise<void>;
  qaResult?: QAResult;
  recommend: () => Promise<void>;
  pathResult?: LearningPathResult;
}) {
  return (
    <div className="panel-stack">
      <section className="tool-section">
        <h3><CheckCircle2 size={18} /> 知识点详情</h3>
        {selectedNode ? (
          <>
            <div className="node-detail">
              <b>{selectedNode.name}</b>
              <span>{selectedNode.definition}</span>
              <small>{selectedNode.example}</small>
            </div>
            <button className="primary" onClick={() => toggleMastered(selectedNode)}>
              {selectedNode.mastered ? '取消掌握标记' : '标记为已掌握'}
            </button>
          </>
        ) : (
          <p>点击图谱节点查看详情。</p>
        )}
      </section>
      <section className="tool-section">
        <h3><Route size={18} /> 学习路径推荐</h3>
        <button className="primary" onClick={recommend}>生成下一步路径</button>
        <div className="recommend-list">
          {pathResult?.recommendations.map((item) => (
            <div key={item.node.id} className="recommend-item">
              <b>{item.node.name}</b>
              <span>{item.reason}</span>
            </div>
          ))}
        </div>
      </section>
      <section className="tool-section">
        <h3><Bot size={18} /> 智能问答</h3>
        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} />
        <button className="primary" onClick={ask}><Send size={16} /> 提问</button>
        {qaResult && (
          <div className="answer">
            <p>{qaResult.answer}</p>
            <small>引用：{qaResult.citations.map((node) => node.name).join('、')}</small>
          </div>
        )}
      </section>
    </div>
  );
}
