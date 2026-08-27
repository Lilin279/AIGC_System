import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bot,
  BookOpen,
  CheckCircle2,
  FileText,
  FileUp,
  Link2,
  LogOut,
  Network,
  Plus,
  Route,
  Save,
  Send,
  Trash2,
  UserRound,
} from 'lucide-react';
import { api, hasAccessToken, setAccessToken } from './api';
import GraphView from './components/GraphView';
import type {
  Course,
  DocumentInfo,
  KnowledgeEdge,
  KnowledgeGraph,
  KnowledgeNode,
  LearningPathResult,
  QAResult,
  RelationType,
  User,
} from './types';

const emptyGraph: KnowledgeGraph = { nodes: [], edges: [] };
const relationOptions: Array<{ value: RelationType; label: string }> = [
  { value: 'contains', label: '包含关系' },
  { value: 'prerequisite', label: '前置关系' },
  { value: 'related', label: '相关关系' },
];

const blankNode: Omit<KnowledgeNode, 'id'> = {
  name: '',
  type: 'concept',
  definition: '',
  example: '',
  resources: [],
  mastered: false,
};

export default function App() {
  const [user, setUser] = useState<User | undefined>();
  const [authReady, setAuthReady] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [loginName, setLoginName] = useState('teacher');
  const [loginPassword, setLoginPassword] = useState('Teacher123!');
  const [registerForm, setRegisterForm] = useState({ username: '', password: '', name: '', organization: '金扬智能示范学校' });
  const [authError, setAuthError] = useState('');
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState('');
  const [graph, setGraph] = useState<KnowledgeGraph>(emptyGraph);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | undefined>();
  const [selectedEdgeId, setSelectedEdgeId] = useState('');
  const [status, setStatus] = useState('请先登录系统。');
  const [question, setQuestion] = useState('函数和参数传递有什么关系？');
  const [qaResult, setQaResult] = useState<QAResult | undefined>();
  const [pathResult, setPathResult] = useState<LearningPathResult | undefined>();
  const [pathEdgeIds, setPathEdgeIds] = useState<string[]>([]);
  const [courseForm, setCourseForm] = useState({ name: '', description: '', status: 'draft' as Course['status'] });
  const [nodeForm, setNodeForm] = useState<Omit<KnowledgeNode, 'id'>>(blankNode);
  const [edgeForm, setEdgeForm] = useState<Omit<KnowledgeEdge, 'id'>>({
    source: '',
    target: '',
    relation: 'prerequisite',
    label: '前置关系',
  });

  const selectedCourse = courses.find((course) => course.id === courseId);
  const selectedEdge = graph.edges.find((edge) => edge.id === selectedEdgeId);
  const masteredIds = useMemo(() => graph.nodes.filter((node) => node.mastered).map((node) => node.id), [graph.nodes]);

  const refreshCourses = useCallback(async () => {
    const data = await api.listCourses();
    setCourses(data);
    setCourseId((current) => data.some((course) => course.id === current) ? current : data[0]?.id || '');
  }, []);

  useEffect(() => {
    if (!hasAccessToken()) {
      setAuthReady(true);
      return;
    }
    api.me()
      .then(setUser)
      .catch(() => setAccessToken(''))
      .finally(() => setAuthReady(true));
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => {
      setUser(undefined);
      setCourses([]);
      setCourseId('');
      setGraph(emptyGraph);
      setDocuments([]);
      setAuthError('登录已失效，请重新登录。');
    };
    window.addEventListener('coursegraph:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('coursegraph:unauthorized', handleUnauthorized);
  }, []);

  const refreshGraph = useCallback(async (id: string) => {
    if (!id) return;
    const data = await api.getGraph(id);
    setGraph(data);
    setSelectedNode((current) => data.nodes.find((node) => node.id === current?.id) ?? data.nodes[0]);
  }, []);

  const refreshDocuments = useCallback(async (id: string) => {
    if (!id) return;
    const data = await api.listDocuments(id);
    setDocuments(data);
  }, []);

  useEffect(() => {
    if (!user) return;
    refreshCourses()
      .then(() => setStatus('工作台已就绪。'))
      .catch((error) => setStatus(`后端连接失败：${error.message}`));
  }, [refreshCourses, user]);

  useEffect(() => {
    if (!courseId) return;
    refreshGraph(courseId).catch((error) => setStatus(`图谱加载失败：${error.message}`));
    refreshDocuments(courseId).catch(() => setDocuments([]));
  }, [courseId, refreshDocuments, refreshGraph]);

  useEffect(() => {
    if (!selectedCourse) return;
    setCourseForm({
      name: selectedCourse.name,
      description: selectedCourse.description,
      status: selectedCourse.status,
    });
  }, [selectedCourse]);

  useEffect(() => {
    if (!selectedNode) return;
    setNodeForm({
      name: selectedNode.name,
      type: selectedNode.type,
      definition: selectedNode.definition,
      example: selectedNode.example,
      resources: selectedNode.resources,
      mastered: selectedNode.mastered,
    });
  }, [selectedNode]);

  useEffect(() => {
    if (!selectedEdge) return;
    setEdgeForm({
      source: selectedEdge.source,
      target: selectedEdge.target,
      relation: selectedEdge.relation,
      label: selectedEdge.label,
    });
  }, [selectedEdge]);

  const login = async () => {
    setAuthError('');
    try {
      const result = await api.login(loginName, loginPassword);
      setAccessToken(result.token);
      setUser(result.user);
      setStatus(`${result.user.name} 已登录。`);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '登录失败');
    }
  };

  const register = async () => {
    setAuthError('');
    try {
      const result = await api.register(registerForm);
      setAccessToken(result.token);
      setUser(result.user);
      setStatus(`${result.user.name}，欢迎开始学习。`);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '注册失败');
    }
  };

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setAccessToken('');
    setUser(undefined);
    setCourses([]);
    setCourseId('');
    setGraph(emptyGraph);
    setDocuments([]);
  };

  const createCourse = async () => {
    if (!courseForm.name.trim()) return;
    const course = await api.createCourse(courseForm);
    await refreshCourses();
    setCourseId(course.id);
    setGraph(emptyGraph);
    setDocuments([]);
    setStatus('新课程已创建，可继续上传资料并构建图谱。');
  };

  const updateCourse = async () => {
    if (!selectedCourse) return;
    const updated = await api.updateCourse({ id: selectedCourse.id, ...courseForm });
    await refreshCourses();
    setCourseId(updated.id);
    setStatus('课程信息已保存。');
  };

  const deleteCourse = async () => {
    if (!selectedCourse) return;
    if (!window.confirm(`确认删除课程“${selectedCourse.name}”吗？相关资料、图谱和学习进度也会删除。`)) return;
    await api.deleteCourse(selectedCourse.id);
    setCourseId('');
    setGraph(emptyGraph);
    setDocuments([]);
    await refreshCourses();
    setStatus('课程已删除。');
  };

  const uploadDocument = async (file?: File) => {
    if (!courseId || !file) return;
    setStatus('正在上传并解析课程资料...');
    await api.uploadDocument(courseId, file);
    await refreshDocuments(courseId);
    setStatus('资料已解析，正在生成课程知识图谱...');
    const result = await api.extract(courseId);
    setGraph(result.graph);
    setStatus(result.message);
    await refreshCourses();
  };

  const deleteDocument = async (documentId: string) => {
    if (!courseId) return;
    if (!window.confirm('确认删除这份课程资料吗？')) return;
    await api.deleteDocument(courseId, documentId);
    await refreshDocuments(courseId);
    await refreshCourses();
    setStatus('资料已删除。');
  };

  const saveNode = async () => {
    if (!courseId || !nodeForm.name.trim()) return;
    const saved = selectedNode
      ? await api.updateNode(courseId, { id: selectedNode.id, ...nodeForm })
      : await api.addNode(courseId, nodeForm);
    await refreshGraph(courseId);
    setSelectedNode(saved);
    setStatus('知识点已保存。');
  };

  const newNode = () => {
    setSelectedNode(undefined);
    setNodeForm(blankNode);
  };

  const deleteNode = async () => {
    if (!courseId || !selectedNode) return;
    if (!window.confirm(`确认删除知识点“${selectedNode.name}”及其相关关系吗？`)) return;
    await api.deleteNode(courseId, selectedNode.id);
    setSelectedNode(undefined);
    await refreshGraph(courseId);
    setStatus('知识点及相关关系已删除。');
  };

  const saveEdge = async () => {
    if (!courseId || !edgeForm.source || !edgeForm.target || edgeForm.source === edgeForm.target) return;
    const saved = selectedEdge
      ? await api.updateEdge(courseId, { id: selectedEdge.id, ...edgeForm })
      : await api.addEdge(courseId, edgeForm);
    setSelectedEdgeId(saved.id);
    await refreshGraph(courseId);
    setStatus('知识关系已保存。');
  };

  const newEdge = () => {
    setSelectedEdgeId('');
    setEdgeForm({
      source: graph.nodes[0]?.id ?? '',
      target: graph.nodes[1]?.id ?? '',
      relation: 'prerequisite',
      label: '前置关系',
    });
  };

  const deleteEdge = async () => {
    if (!courseId || !selectedEdge) return;
    if (!window.confirm('确认删除这条知识关系吗？')) return;
    await api.deleteEdge(courseId, selectedEdge.id);
    setSelectedEdgeId('');
    await refreshGraph(courseId);
    setStatus('知识关系已删除。');
  };

  const toggleMastered = async (node: KnowledgeNode) => {
    if (!courseId) return;
    const updated = await api.updateProgress(courseId, node.id, !node.mastered);
    await refreshGraph(courseId);
    setSelectedNode(updated);
  };

  const ask = async () => {
    if (!courseId || !question.trim()) return;
    setStatus('正在基于课程图谱生成回答...');
    const result = await api.qa(courseId, question);
    setQaResult(result);
    setStatus('问答完成。');
  };

  const recommend = async () => {
    if (!courseId) return;
    const result = await api.learningPath(courseId);
    setPathResult(result);
    setPathEdgeIds(result.path_edges.map((edge) => edge.id));
    setStatus('已生成下一步学习路径。');
  };

  const withError = useCallback(async (action: () => Promise<void>) => {
    try {
      await action();
    } catch (error) {
      setStatus(`操作失败：${error instanceof Error ? error.message : '请稍后重试'}`);
    }
  }, []);

  if (!authReady) {
    return <main className="login-page"><p className="auth-loading">正在恢复登录状态...</p></main>;
  }

  if (!user) {
    return (
      <main className="login-page">
        <section className="login-panel">
          <div>
            <p className="eyebrow">CourseGraph AI</p>
            <h1>AIGC 课程知识图谱学习导航系统</h1>
            <p>面向高校课程建设的知识图谱构建、学习导航与智能问答平台。</p>
          </div>
          <div className="auth-tabs" role="tablist" aria-label="账号操作">
            <button className={authMode === 'login' ? 'active' : ''} onClick={() => { setAuthMode('login'); setAuthError(''); }}>账号登录</button>
            <button className={authMode === 'register' ? 'active' : ''} onClick={() => { setAuthMode('register'); setAuthError(''); }}>学生注册</button>
          </div>
          {authMode === 'login' ? (
            <>
              <label>用户名<input autoComplete="username" value={loginName} onChange={(event) => setLoginName(event.target.value)} /></label>
              <label>密码<input type="password" autoComplete="current-password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && login()} /></label>
              <button className="primary" onClick={login}><UserRound size={16} /> 登录</button>
              <div className="demo-accounts">
                <span>演示账号</span>
                <button onClick={() => { setLoginName('teacher'); setLoginPassword('Teacher123!'); }}>教师</button>
                <button onClick={() => { setLoginName('student'); setLoginPassword('Student123!'); }}>学生</button>
                <button onClick={() => { setLoginName('admin'); setLoginPassword('Admin123!'); }}>管理员</button>
              </div>
            </>
          ) : (
            <>
              <label>用户名<input autoComplete="username" value={registerForm.username} onChange={(event) => setRegisterForm({ ...registerForm, username: event.target.value })} /></label>
              <label>姓名<input value={registerForm.name} onChange={(event) => setRegisterForm({ ...registerForm, name: event.target.value })} /></label>
              <label>学校 / 机构<input value={registerForm.organization} onChange={(event) => setRegisterForm({ ...registerForm, organization: event.target.value })} /></label>
              <label>密码<input type="password" autoComplete="new-password" placeholder="至少 8 个字符" value={registerForm.password} onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })} /></label>
              <button className="primary" onClick={register}><UserRound size={16} /> 创建学生账号</button>
            </>
          )}
          {authError && <p className="form-error" role="alert">{authError}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>AIGC 课程知识图谱学习导航系统</h1>
          <span>{user.organization} · {user.name} · {user.role === 'teacher' ? '教师端' : user.role === 'student' ? '学生端' : '管理端'}</span>
        </div>
        <div className="top-actions">
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
          <button className="ghost" onClick={logout} title="退出登录">
            <LogOut size={18} />
          </button>
        </div>
      </header>

      <section className="workspace">
        <aside className="sidebar">
          <div className="metric-panel">
            {user.role === 'student' ? (
              <>
                <span>知识点</span>
                <strong>{graph.nodes.length}</strong>
                <span>关系</span>
                <strong>{graph.edges.length}</strong>
                <span>已掌握</span>
                <strong>{masteredIds.length}</strong>
              </>
            ) : (
              <>
                <span>课程</span>
                <strong>{courses.length}</strong>
                <span>资料</span>
                <strong>{documents.length}</strong>
                <span>知识点</span>
                <strong>{graph.nodes.length}</strong>
                <span>关系</span>
                <strong>{graph.edges.length}</strong>
              </>
            )}
          </div>
          <p className="status">{status}</p>
        </aside>

        <section className="graph-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">当前课程</p>
              <h2>{selectedCourse?.name ?? '暂无课程'}</h2>
            </div>
            <div className="course-summary">
              {selectedCourse && <small className={`status-badge ${selectedCourse.status}`}>{selectedCourse.status === 'published' ? '已发布' : selectedCourse.status === 'archived' ? '已归档' : '草稿'}</small>}
              <span>{selectedCourse?.description ?? (user.role === 'student' ? '当前暂无已发布课程。' : '请开设一门新课程。')}</span>
            </div>
          </div>
          <GraphView graph={graph} selectedNodeId={selectedNode?.id} pathEdgeIds={pathEdgeIds} onSelectNode={setSelectedNode} />
        </section>

        <aside className="detail-panel">
          {user.role === 'student' ? (
            <StudentPanel
              selectedNode={selectedNode}
              toggleMastered={(node) => withError(() => toggleMastered(node))}
              question={question}
              setQuestion={setQuestion}
              ask={() => withError(ask)}
              qaResult={qaResult}
              recommend={() => withError(recommend)}
              pathResult={pathResult}
            />
          ) : (
            <TeacherPanel
              selectedCourse={selectedCourse}
              courseForm={courseForm}
              setCourseForm={setCourseForm}
              createCourse={() => withError(createCourse)}
              updateCourse={() => withError(updateCourse)}
              deleteCourse={() => withError(deleteCourse)}
              documents={documents}
              uploadDocument={(file) => withError(() => uploadDocument(file))}
              deleteDocument={(id) => withError(() => deleteDocument(id))}
              graph={graph}
              selectedNode={selectedNode}
              nodeForm={nodeForm}
              setNodeForm={setNodeForm}
              newNode={newNode}
              saveNode={() => withError(saveNode)}
              deleteNode={() => withError(deleteNode)}
              selectedEdgeId={selectedEdgeId}
              setSelectedEdgeId={setSelectedEdgeId}
              edgeForm={edgeForm}
              setEdgeForm={setEdgeForm}
              newEdge={newEdge}
              saveEdge={() => withError(saveEdge)}
              deleteEdge={() => withError(deleteEdge)}
            />
          )}
        </aside>
      </section>
    </main>
  );
}

function TeacherPanel(props: {
  selectedCourse?: Course;
  courseForm: Pick<Course, 'name' | 'description' | 'status'>;
  setCourseForm: (value: Pick<Course, 'name' | 'description' | 'status'>) => void;
  createCourse: () => Promise<void>;
  updateCourse: () => Promise<void>;
  deleteCourse: () => Promise<void>;
  documents: DocumentInfo[];
  uploadDocument: (file?: File) => Promise<void>;
  deleteDocument: (id: string) => Promise<void>;
  graph: KnowledgeGraph;
  selectedNode?: KnowledgeNode;
  nodeForm: Omit<KnowledgeNode, 'id'>;
  setNodeForm: (value: Omit<KnowledgeNode, 'id'>) => void;
  newNode: () => void;
  saveNode: () => Promise<void>;
  deleteNode: () => Promise<void>;
  selectedEdgeId: string;
  setSelectedEdgeId: (id: string) => void;
  edgeForm: Omit<KnowledgeEdge, 'id'>;
  setEdgeForm: (value: Omit<KnowledgeEdge, 'id'>) => void;
  newEdge: () => void;
  saveEdge: () => Promise<void>;
  deleteEdge: () => Promise<void>;
}) {
  return (
    <div className="panel-stack">
      <section className="tool-section">
        <h3><Plus size={18} /> 开课与课程管理</h3>
        <label>课程名称<input value={props.courseForm.name} onChange={(event) => props.setCourseForm({ ...props.courseForm, name: event.target.value })} /></label>
        <label>课程简介<textarea value={props.courseForm.description} onChange={(event) => props.setCourseForm({ ...props.courseForm, description: event.target.value })} /></label>
        <label>发布状态<select value={props.courseForm.status} onChange={(event) => props.setCourseForm({ ...props.courseForm, status: event.target.value as Course['status'] })}>
          <option value="draft">草稿</option>
          <option value="published">已发布</option>
          <option value="archived">已归档</option>
        </select></label>
        <div className="button-row">
          <button className="primary" onClick={props.createCourse}><Plus size={16} /> 开设新课</button>
          <button className="secondary" onClick={props.updateCourse} disabled={!props.selectedCourse}><Save size={16} /> 保存课程</button>
          <button className="danger" onClick={props.deleteCourse} disabled={!props.selectedCourse}><Trash2 size={16} /> 删除课程</button>
        </div>
      </section>

      <section className="tool-section">
        <h3><FileUp size={18} /> 资料中心</h3>
        <input type="file" accept=".txt,.md,.markdown,.pdf,.docx,.pptx" onChange={(event) => props.uploadDocument(event.target.files?.[0])} />
        <p>支持 PDF、Word、PPT、TXT、Markdown 课程资料，解析后进入知识抽取流程。</p>
        <div className="list">
          {props.documents.map((document) => (
            <div className="list-item" key={document.id}>
              <FileText size={16} />
              <span>{document.filename}</span>
              <small>{document.format.toUpperCase()} · {document.parsed_chars} 字</small>
              <button className="icon-button" onClick={() => props.deleteDocument(document.id)} title="删除资料"><Trash2 size={15} /></button>
            </div>
          ))}
        </div>
      </section>

      <section className="tool-section">
        <h3><Network size={18} /> 知识点编辑</h3>
        <div className="button-row">
          <button className="secondary" onClick={props.newNode}><Plus size={16} /> 新建知识点</button>
          <button className="primary" onClick={props.saveNode}><Save size={16} /> 保存知识点</button>
          <button className="danger" onClick={props.deleteNode} disabled={!props.selectedNode}><Trash2 size={16} /> 删除</button>
        </div>
        <label>名称<input value={props.nodeForm.name} onChange={(event) => props.setNodeForm({ ...props.nodeForm, name: event.target.value })} /></label>
        <label>类型<input value={props.nodeForm.type} onChange={(event) => props.setNodeForm({ ...props.nodeForm, type: event.target.value })} /></label>
        <label>定义<textarea value={props.nodeForm.definition} onChange={(event) => props.setNodeForm({ ...props.nodeForm, definition: event.target.value })} /></label>
        <label>示例<textarea value={props.nodeForm.example} onChange={(event) => props.setNodeForm({ ...props.nodeForm, example: event.target.value })} /></label>
      </section>

      <section className="tool-section">
        <h3><Link2 size={18} /> 关系编辑</h3>
        <div className="button-row">
          <button className="secondary" onClick={props.newEdge}><Plus size={16} /> 新建关系</button>
          <button className="primary" onClick={props.saveEdge}><Save size={16} /> 保存关系</button>
          <button className="danger" onClick={props.deleteEdge} disabled={!props.selectedEdgeId}><Trash2 size={16} /> 删除</button>
        </div>
        <label>已有关系<select value={props.selectedEdgeId} onChange={(event) => props.setSelectedEdgeId(event.target.value)}>
          <option value="">新建关系</option>
          {props.graph.edges.map((edge) => (
            <option key={edge.id} value={edge.id}>{edge.label}：{nodeName(props.graph, edge.source)} -&gt; {nodeName(props.graph, edge.target)}</option>
          ))}
        </select></label>
        <label>源知识点<select value={props.edgeForm.source} onChange={(event) => props.setEdgeForm({ ...props.edgeForm, source: event.target.value })}>
          <option value="">请选择</option>
          {props.graph.nodes.map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}
        </select></label>
        <label>目标知识点<select value={props.edgeForm.target} onChange={(event) => props.setEdgeForm({ ...props.edgeForm, target: event.target.value })}>
          <option value="">请选择</option>
          {props.graph.nodes.map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}
        </select></label>
        <label>关系类型<select value={props.edgeForm.relation} onChange={(event) => {
          const relation = event.target.value as RelationType;
          props.setEdgeForm({ ...props.edgeForm, relation, label: relationOptions.find((item) => item.value === relation)?.label ?? '' });
        }}>
          {relationOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select></label>
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

function nodeName(graph: KnowledgeGraph, id: string) {
  return graph.nodes.find((node) => node.id === id)?.name ?? id;
}
