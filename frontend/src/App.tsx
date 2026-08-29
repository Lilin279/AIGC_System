import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, BookOpen, Bot, Check, ChevronRight, CircleUserRound, ClipboardList, Database,
  FileText, FileUp, GraduationCap, History, LayoutDashboard, LifeBuoy, Link2, LogOut,
  Network, Plus, RefreshCw, Route, Save, School, Search, Send, Settings, ShieldCheck,
  Trash2, Upload, UserCheck, Users, X,
} from 'lucide-react';
import { api, hasAccessToken, setAccessToken } from './api';
import GraphView from './components/GraphView';
import type {
  AIStatus, Classroom, Course, DashboardStats, DiagnosisResult, DocumentImpact, DocumentInfo,
  ExerciseResult, ExtractionJob, GraphQuality, GraphVersion, ImportCommitResult, ImportPreview,
  KnowledgeEdge, KnowledgeGraph, KnowledgeNode, LearningPathResult, QAResult, RelationType,
  Ticket, User,
} from './types';

const emptyGraph: KnowledgeGraph = { nodes: [], edges: [] };
const emptyPathEdgeIds: string[] = [];
const relationLabels: Record<RelationType, string> = {
  contains: '包含关系', prerequisite: '前置关系', related: '相关关系',
};
type View = 'home' | 'courses' | 'classes' | 'learning' | 'users' | 'tickets' | 'audit' | 'profile';

export default function App() {
  const [user, setUser] = useState<User>();
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<View>('home');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!hasAccessToken()) { setReady(true); return; }
    api.me().then((value) => { setUser(value); setView(defaultView(value)); })
      .catch(() => setAccessToken('')).finally(() => setReady(true));
  }, []);

  useEffect(() => {
    const expired = () => { setUser(undefined); setMessage('登录已失效，请重新登录。'); };
    window.addEventListener('coursegraph:unauthorized', expired);
    return () => window.removeEventListener('coursegraph:unauthorized', expired);
  }, []);

  const run = useCallback(async (action: () => Promise<void>, success = '') => {
    try { await action(); if (success) setMessage(success); }
    catch (error) { setMessage(error instanceof Error ? error.message : '操作失败，请稍后重试'); }
  }, []);

  if (!ready) return <main className="center-page">正在恢复会话...</main>;
  if (!user) return <AuthScreen initialMessage={message} onAuthenticated={(next) => { setUser(next); setView(defaultView(next)); }} />;

  const pending = user.role === 'teacher' && user.account_status !== 'active';
  const nav = pending ? pendingNav : roleNav[user.role];

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setAccessToken('');
    setMessage('');
    setUser(undefined);
  };

  return (
    <main className="portal-shell">
      <aside className="portal-nav">
        <div className="brand"><Network size={24} /><div><b>CourseGraph</b><span>课程知识图谱平台</span></div></div>
        <div className="role-chip">{roleName(user.role)}端</div>
        <nav>
          {nav.map((item) => (
            <button key={item.view} className={view === item.view ? 'active' : ''} onClick={() => setView(item.view)}>
              <item.icon size={18} /><span>{item.label}</span><ChevronRight size={14} />
            </button>
          ))}
        </nav>
        <button className="nav-logout" onClick={logout}><LogOut size={18} />退出登录</button>
      </aside>

      <section className="portal-main">
        <header className="portal-topbar">
          <div><h1>{nav.find((item) => item.view === view)?.label ?? '工作台'}</h1><p>{user.organization}</p></div>
          <button className="user-menu" onClick={() => setView('profile')}>
            <span>{user.name.slice(0, 1)}</span><div><b>{user.name}</b><small>{roleName(user.role)}</small></div>
          </button>
        </header>
        {message && <div className="notice" role="status"><Activity size={16} />{message}<button onClick={() => setMessage('')}><X size={15} /></button></div>}

        <div className="content-area">
          {pending && view === 'home' && <PendingReview user={user} />}
          {!pending && user.role === 'teacher' && view === 'home' && <TeacherOverview run={run} />}
          {!pending && user.role === 'teacher' && view === 'courses' && <CourseStudio run={run} />}
          {!pending && user.role === 'teacher' && view === 'classes' && <ClassroomCenter run={run} />}
          {!pending && user.role === 'student' && (view === 'home' || view === 'learning') && <StudentLearning run={run} />}
          {!pending && user.role === 'admin' && view === 'home' && <AdminOverview run={run} />}
          {!pending && user.role === 'admin' && view === 'users' && <AdminUsers run={run} />}
          {!pending && user.role === 'admin' && view === 'classes' && <AdminResources mode="classes" run={run} />}
          {!pending && user.role === 'admin' && view === 'courses' && <AdminResources mode="courses" run={run} />}
          {!pending && user.role === 'admin' && view === 'audit' && <AuditLog run={run} />}
          {view === 'tickets' && <TicketCenter user={user} run={run} />}
          {view === 'profile' && <ProfileCenter user={user} onUser={setUser} run={run} />}
        </div>
      </section>
    </main>
  );
}

const roleNav = {
  teacher: [
    { view: 'home' as View, label: '教学概览', icon: LayoutDashboard },
    { view: 'courses' as View, label: '课程工作室', icon: BookOpen },
    { view: 'classes' as View, label: '教学班级', icon: Users },
    { view: 'tickets' as View, label: '反馈工单', icon: LifeBuoy },
    { view: 'profile' as View, label: '个人中心', icon: CircleUserRound },
  ],
  student: [
    { view: 'home' as View, label: '学习空间', icon: GraduationCap },
    { view: 'tickets' as View, label: '反馈工单', icon: LifeBuoy },
    { view: 'profile' as View, label: '个人中心', icon: CircleUserRound },
  ],
  admin: [
    { view: 'home' as View, label: '学校概览', icon: LayoutDashboard },
    { view: 'users' as View, label: '用户与审核', icon: UserCheck },
    { view: 'classes' as View, label: '全部班级', icon: School },
    { view: 'courses' as View, label: '全部课程', icon: BookOpen },
    { view: 'tickets' as View, label: '工单中心', icon: LifeBuoy },
    { view: 'audit' as View, label: '审计日志', icon: History },
    { view: 'profile' as View, label: '个人中心', icon: CircleUserRound },
  ],
};
const pendingNav = [
  { view: 'home' as View, label: '审核状态', icon: ShieldCheck },
  { view: 'tickets' as View, label: '反馈工单', icon: LifeBuoy },
  { view: 'profile' as View, label: '个人中心', icon: CircleUserRound },
];

function AuthScreen({ initialMessage, onAuthenticated }: { initialMessage: string; onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<'login' | 'student' | 'teacher'>('login');
  const [form, setForm] = useState({ username: 'teacher', password: 'Teacher123!', name: '', organization: '金扬智能示范学校', email: '', phone: '', department: '计算机学院', title: '讲师' });
  const [error, setError] = useState(initialMessage);
  const submit = async () => {
    try {
      const result = mode === 'login' ? await api.login(form.username, form.password)
        : mode === 'teacher' ? await api.registerTeacher(form) : await api.registerStudent(form);
      setAccessToken(result.token); onAuthenticated(result.user);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败'); }
  };
  return (
    <main className="auth-page">
      <section className="auth-intro"><Network size={36} /><h1>CourseGraph AI</h1><p>课程知识图谱构建、教学班管理与可溯源智能学习平台</p><div><span><Check size={16} />课件来源可追溯</span><span><Check size={16} />班级数据相互隔离</span><span><Check size={16} />AIGC 候选图谱审核</span></div></section>
      <section className="auth-panel">
        <div className="segmented">{(['login', 'student', 'teacher'] as const).map((item) => <button key={item} className={mode === item ? 'active' : ''} onClick={() => setMode(item)}>{item === 'login' ? '登录' : item === 'student' ? '学生注册' : '教师申请'}</button>)}</div>
        <h2>{mode === 'login' ? '欢迎回来' : mode === 'student' ? '创建学生账号' : '提交教师入驻申请'}</h2>
        {mode !== 'login' && <label>姓名<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>}
        <label>用户名<input autoComplete="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label>密码<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && submit()} /></label>
        {mode === 'teacher' && <><label>邮箱<input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label><div className="field-grid"><label>院系<input value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></label><label>职称<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label></div></>}
        <button className="primary wide" onClick={submit}>{mode === 'login' ? '登录系统' : mode === 'student' ? '注册并开始学习' : '提交申请'}</button>
        {mode === 'login' && <div className="demo-logins"><span>演示身份</span><button onClick={() => setForm({ ...form, username: 'teacher', password: 'Teacher123!' })}>教师</button><button onClick={() => setForm({ ...form, username: 'student', password: 'Student123!' })}>学生</button><button onClick={() => setForm({ ...form, username: 'admin', password: 'Admin123!' })}>管理员</button></div>}
        {error && <p className="form-error">{error}</p>}
      </section>
    </main>
  );
}

function TeacherOverview({ run }: RunProps) {
  const [courses, setCourses] = useState<Course[]>([]); const [classes, setClasses] = useState<Classroom[]>([]);
  const load = useCallback(() => run(async () => { setCourses(await api.listCourses()); setClasses(await api.listClassrooms()); }), [run]);
  useEffect(() => { void load(); }, [load]);
  const students = classes.reduce((sum, item) => sum + item.student_count, 0);
  return <><PageHeading title="教学概览" description="课程内容与教学班分开管理，图谱更新后自动服务于关联班级。" /><MetricGrid items={[['课程', courses.length], ['教学班', classes.length], ['在班学生', students], ['平均进度', `${Math.round(classes.reduce((s, c) => s + c.average_progress, 0) / Math.max(1, classes.length))}%`]]} /><section className="surface"><h3>近期教学班</h3><DataTable headers={['班级', '课程', '学期', '人数', '平均进度']} rows={classes.slice(0, 6).map((item) => [item.name, item.course_name, item.semester, item.student_count, `${item.average_progress}%`])} /></section></>;
}

function CourseStudio({ run }: RunProps) {
  const [courses, setCourses] = useState<Course[]>([]); const [courseId, setCourseId] = useState('');
  const [graph, setGraph] = useState<KnowledgeGraph>(emptyGraph); const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [jobs, setJobs] = useState<ExtractionJob[]>([]); const [versions, setVersions] = useState<GraphVersion[]>([]);
  const [quality, setQuality] = useState<GraphQuality>(); const [selected, setSelected] = useState<KnowledgeNode>();
  const [aiStatus, setAiStatus] = useState<AIStatus>();
  const [nodeForm, setNodeForm] = useState({ name: '', type: 'concept', definition: '', example: '', resources: [] as string[], mastered: false });
  const [edgeForm, setEdgeForm] = useState<{ source: string; target: string; relation: RelationType; label: string }>({ source: '', target: '', relation: 'prerequisite', label: '前置关系' });
  const [newCourse, setNewCourse] = useState({ name: '', description: '', status: 'draft' as Course['status'] });
  const [deleteDoc, setDeleteDoc] = useState<{ doc: DocumentInfo; impact: DocumentImpact; rollback: boolean }>();
  const course = courses.find((item) => item.id === courseId);
  const hasCandidateVersion = versions.some((version) => version.status === 'candidate');
  const loadCourses = useCallback(async () => { const data = await api.listCourses(); setCourses(data); setCourseId((old) => data.some((c) => c.id === old) ? old : data[0]?.id ?? ''); }, []);
  const loadCourse = useCallback(async (id: string) => { if (!id) return; const [g, d, j, v, q] = await Promise.all([api.getGraph(id), api.listDocuments(id), api.extractionJobs(id), api.graphVersions(id), api.graphQuality(id)]); setGraph(g); setDocs(d); setJobs(j); setVersions(v); setQuality(q); setSelected((old) => g.nodes.find((n) => n.id === old?.id) ?? g.nodes[0]); }, []);
  useEffect(() => { void run(loadCourses); }, [loadCourses, run]);
  useEffect(() => { void run(() => loadCourse(courseId)); }, [courseId, loadCourse, run]);
  useEffect(() => { void run(async () => setAiStatus(await api.aiStatus())); }, [run]);
  useEffect(() => { if (selected) setNodeForm({ ...selected }); }, [selected]);

  const startExtraction = async () => { const job = await api.extract(courseId); setJobs((old) => [job, ...old]); const timer = window.setInterval(async () => { const latest = await api.extractionJob(job.id); setJobs((old) => old.map((item) => item.id === latest.id ? latest : item)); if (['review', 'completed', 'failed'].includes(latest.status)) { window.clearInterval(timer); await loadCourse(courseId); } }, 900); };
  const extract = () => run(startExtraction, '抽取任务已创建，请留意审核区。');
  const saveNode = () => run(async () => { if (selected) await api.updateNode(courseId, { id: selected.id, ...nodeForm }); else await api.addNode(courseId, nodeForm); await loadCourse(courseId); }, '知识点已保存并生成新版本。');
  const saveEdge = () => run(async () => { await api.addEdge(courseId, edgeForm); await loadCourse(courseId); }, '知识关系已保存。');
  const openDelete = (doc: DocumentInfo) => run(async () => setDeleteDoc({ doc, impact: await api.documentImpact(courseId, doc.id), rollback: true }));
  return <>
    <PageHeading title="课程工作室" description="课件生成候选图谱，教师审核确认后才会影响学生看到的正式版本。" actions={<button className="secondary" onClick={() => void loadCourse(courseId)}><RefreshCw size={16} />刷新</button>} />
    <div className="studio-toolbar"><select value={courseId} onChange={(e) => setCourseId(e.target.value)}>{courses.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><span className={`badge ${course?.status}`}>{course?.status === 'published' ? '已发布' : '草稿'}</span>{course?.source_incomplete && <span className="badge warning">来源不完整</span>}<div className="quality">图谱质量 <b>{quality?.score ?? 0}</b>/100</div></div>
    <div className="studio-grid">
      <section className="surface graph-workspace"><div className="surface-title"><div><h3>{course?.name ?? '暂无课程'}</h3><p>{graph.nodes.length} 个知识点 · {graph.edges.length} 条关系</p></div></div><GraphView graph={graph} selectedNodeId={selected?.id} pathEdgeIds={emptyPathEdgeIds} onSelectNode={setSelected} /></section>
      <aside className="studio-side">
        <details className="surface" open><summary><Plus size={17} />新建课程</summary><label>名称<input value={newCourse.name} onChange={(e) => setNewCourse({ ...newCourse, name: e.target.value })} /></label><label>简介<textarea value={newCourse.description} onChange={(e) => setNewCourse({ ...newCourse, description: e.target.value })} /></label><button className="primary" onClick={() => run(async () => { const created = await api.createCourse(newCourse); await loadCourses(); setCourseId(created.id); }, '课程已创建。')}><Plus size={16} />开设课程</button></details>
        <details className="surface" open><summary><FileUp size={17} />课件与抽取</summary>{aiStatus && <div className={`ai-mode ${aiStatus.configured ? 'online' : 'offline'}`}><Bot size={15} /><span>{aiStatus.configured ? `DeepSeek 真 AI · ${aiStatus.model}` : '离线演示模式 · 未配置 API Key'}</span></div>}<label className="upload-box"><Upload size={20} /><span>上传 PDF、Word、PPT、TXT 或 Markdown</span><input type="file" accept=".pdf,.docx,.pptx,.txt,.md,.markdown" onChange={(e) => { const file = e.target.files?.[0]; if (file) void run(async () => { await api.uploadDocument(courseId, file); await loadCourse(courseId); await startExtraction(); }, '课件已解析，正在自动生成待审核图谱。'); }} /></label><div className="compact-list">{docs.map((doc) => <div key={doc.id}><FileText size={15} /><span><b>{doc.filename}</b><small>{doc.format.toUpperCase()} · {doc.source_node_count > 0 ? `正式图谱来源节点 ${doc.source_node_count}` : hasCandidateVersion ? '新增内容待审核' : '尚未应用到正式图谱'}</small></span><button title="删除课件" onClick={() => void openDelete(doc)}><Trash2 size={15} /></button></div>)}</div><button className="primary wide" disabled={!docs.length} onClick={extract}><Bot size={16} />重新生成候选图谱</button>{jobs[0] && <div className="job"><div><span>{jobs[0].mode === 'mock' ? '离线演示模式' : 'DeepSeek 模式'}</span><b>{jobs[0].progress}%</b></div><progress value={jobs[0].progress} max={100} /><small>{jobs[0].message}</small></div>}</details>
        <details className="surface" open><summary><ShieldCheck size={17} />候选版本审核</summary>{versions.filter((v) => v.status === 'candidate').map((version) => <div className="review-item" key={version.id}><div><b>版本 {version.version_no}</b><small>{version.summary}</small></div><button className="icon-success" title="确认应用" onClick={() => run(async () => { await api.acceptVersion(courseId, version.id); await loadCourse(courseId); }, '候选图谱已应用。')}><Check size={16} /></button><button className="icon-danger" title="驳回" onClick={() => run(async () => { await api.rejectVersion(courseId, version.id); await loadCourse(courseId); }, '候选图谱已驳回。')}><X size={16} /></button></div>)}{!versions.some((v) => v.status === 'candidate') && <p className="muted">当前没有待审核版本。</p>}<div className="compact-list">{versions.filter((v) => v.status !== 'candidate').slice(0, 4).map((v) => <div key={v.id}><History size={15} /><span><b>v{v.version_no} · {v.status}</b><small>{v.summary}</small></span>{v.status === 'superseded' && <button title="恢复此版本" onClick={() => run(async () => { await api.restoreVersion(courseId, v.id); await loadCourse(courseId); }, '历史版本已恢复。')}><RefreshCw size={15} /></button>}</div>)}</div></details>
        <details className="surface"><summary><Network size={17} />知识点编辑</summary><div className="button-row"><button className="secondary" onClick={() => { setSelected(undefined); setNodeForm({ name: '', type: 'concept', definition: '', example: '', resources: [], mastered: false }); }}><Plus size={15} />新建</button><button className="primary" onClick={saveNode}><Save size={15} />保存</button>{selected && <button className="danger" onClick={() => run(async () => { await api.deleteNode(courseId, selected.id); setSelected(undefined); await loadCourse(courseId); }, '知识点已删除。')}><Trash2 size={15} /></button>}</div><label>名称<input value={nodeForm.name} onChange={(e) => setNodeForm({ ...nodeForm, name: e.target.value })} /></label><label>类型<select value={nodeForm.type} onChange={(e) => setNodeForm({ ...nodeForm, type: e.target.value })}><option value="concept">概念</option><option value="skill">技能</option><option value="chapter">章节</option><option value="example">案例</option></select></label><label>定义<textarea value={nodeForm.definition} onChange={(e) => setNodeForm({ ...nodeForm, definition: e.target.value })} /></label><label>示例<textarea value={nodeForm.example} onChange={(e) => setNodeForm({ ...nodeForm, example: e.target.value })} /></label></details>
        <details className="surface"><summary><Link2 size={17} />关系编辑</summary><label>源知识点<select value={edgeForm.source} onChange={(e) => setEdgeForm({ ...edgeForm, source: e.target.value })}><option value="">请选择</option>{graph.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></label><label>目标知识点<select value={edgeForm.target} onChange={(e) => setEdgeForm({ ...edgeForm, target: e.target.value })}><option value="">请选择</option>{graph.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}</select></label><label>关系<select value={edgeForm.relation} onChange={(e) => { const relation = e.target.value as RelationType; setEdgeForm({ ...edgeForm, relation, label: relationLabels[relation] }); }}>{Object.entries(relationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="primary" onClick={saveEdge}><Link2 size={15} />建立关系</button><div className="compact-list">{graph.edges.slice(0, 8).map((edge) => <div key={edge.id}><span><b>{edge.label}</b><small>{nodeName(graph, edge.source)} → {nodeName(graph, edge.target)}</small></span><button title="删除关系" onClick={() => run(async () => { await api.deleteEdge(courseId, edge.id); await loadCourse(courseId); })}><Trash2 size={14} /></button></div>)}</div></details>
      </aside>
    </div>
    {deleteDoc && <div className="modal-backdrop"><section className="modal"><div className="modal-title"><div><h3>删除课件</h3><p>{deleteDoc.doc.filename}</p></div><button onClick={() => setDeleteDoc(undefined)}><X /></button></div><div className="impact-grid"><span>将移除知识点<b>{deleteDoc.impact.removable_nodes}</b></span><span>将移除关系<b>{deleteDoc.impact.removable_edges}</b></span><span>共享节点保留<b>{deleteDoc.impact.shared_nodes}</b></span><span>人工修订保留<b>{deleteDoc.impact.preserved_manual_nodes}</b></span></div><label className="check-row"><input type="checkbox" checked={deleteDoc.rollback} onChange={(e) => setDeleteDoc({ ...deleteDoc, rollback: e.target.checked })} /><span><b>同步撤销该课件造成的图谱变化</b><small>关闭后保留图谱，但会标记为来源不完整。</small></span></label><div className="modal-actions"><button className="secondary" onClick={() => setDeleteDoc(undefined)}>取消</button><button className="danger" onClick={() => run(async () => { const result = await api.deleteDocument(courseId, deleteDoc.doc.id, deleteDoc.rollback); setDeleteDoc(undefined); await loadCourse(courseId); if (result.needs_reextract) await startExtraction(); }, '课件及对应图谱影响已处理。')}><Trash2 size={16} />确认删除</button></div></section></div>}
  </>;
}

function ClassroomCenter({ run }: RunProps) {
  const [classes, setClasses] = useState<Classroom[]>([]); const [courses, setCourses] = useState<Course[]>([]); const [selectedId, setSelectedId] = useState(''); const [members, setMembers] = useState<User[]>([]);
  const [form, setForm] = useState({ course_id: '', name: '', semester: '2026-2027 第一学期', status: 'active' }); const [preview, setPreview] = useState<ImportPreview>(); const [result, setResult] = useState<ImportCommitResult>();
  const load = useCallback(async () => { const [c, co] = await Promise.all([api.listClassrooms(), api.listCourses()]); setClasses(c); setCourses(co); setSelectedId((old) => c.some((x) => x.id === old) ? old : c[0]?.id ?? ''); setForm((old) => ({ ...old, course_id: old.course_id || co[0]?.id || '' })); }, []);
  useEffect(() => { void run(load); }, [load, run]);
  useEffect(() => { if (selectedId) void run(async () => setMembers(await api.classMembers(selectedId))); }, [run, selectedId]);
  const selected = classes.find((item) => item.id === selectedId);
  return <><PageHeading title="教学班级" description="一门课程可开设多个教学班，学生进度按班级独立保存。" /><div className="two-column"><section className="surface"><h3>我的班级</h3><div className="class-list">{classes.map((item) => <button className={selectedId === item.id ? 'active' : ''} key={item.id} onClick={() => setSelectedId(item.id)}><span><b>{item.name}</b><small>{item.course_name} · {item.semester}</small></span><strong>{item.student_count} 人</strong></button>)}</div><hr /><h3>新建教学班</h3><label>关联课程<select value={form.course_id} onChange={(e) => setForm({ ...form, course_id: e.target.value })}>{courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label>班级名称<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>学期<input value={form.semester} onChange={(e) => setForm({ ...form, semester: e.target.value })} /></label><button className="primary" onClick={() => run(async () => { await api.createClassroom(form); await load(); }, '教学班已创建。')}><Plus size={16} />创建教学班</button></section><section className="surface"><div className="surface-title"><div><h3>{selected?.name ?? '请选择班级'}</h3><p>主教师：{selected?.primary_teacher_name}</p></div>{selected && <div className="join-code"><span>班级码</span><b>{selected.join_code}</b><button title="重置班级码" onClick={() => run(async () => { await api.resetJoinCode(selected.id); await load(); }, '班级码已重置。')}><RefreshCw size={15} /></button></div>}</div><MetricGrid compact items={[['学生', selected?.student_count ?? 0], ['已激活', selected?.active_student_count ?? 0], ['教师', selected?.teacher_count ?? 0], ['平均进度', `${selected?.average_progress ?? 0}%`]]} /><div className="import-row"><label className="secondary file-button"><Upload size={16} />上传 CSV / XLSX<input type="file" accept=".csv,.xlsx" onChange={(e) => { const file = e.target.files?.[0]; if (file && selectedId) void run(async () => { setPreview(await api.previewImport(selectedId, file)); setResult(undefined); }); }} /></label>{preview && <span>有效 {preview.valid} 行，错误 {preview.invalid} 行</span>}{preview && <button className="primary" onClick={() => run(async () => setResult(await api.commitImport(preview.job_id)), '学生导入完成。')}>确认导入</button>}</div>{result && <div className="credentials"><b>临时账号仅展示一次</b>{result.credentials.map((item) => <code key={item.student_no}>{item.student_no} / {item.temporary_password}</code>)}</div>}<DataTable headers={['学号', '姓名', '邮箱', '状态']} rows={members.map((member) => [member.student_no || member.username, member.name, member.email || '-', member.account_status])} /></section></div></>;
}

function StudentLearning({ run }: RunProps) {
  const [classes, setClasses] = useState<Classroom[]>([]); const [classId, setClassId] = useState(''); const [joinCode, setJoinCode] = useState(''); const [graph, setGraph] = useState<KnowledgeGraph>(emptyGraph); const [selected, setSelected] = useState<KnowledgeNode>();
  const [question, setQuestion] = useState('请解释这个知识点与前置知识的关系。'); const [answer, setAnswer] = useState<QAResult>(); const [path, setPath] = useState<LearningPathResult>(); const [diagnosis, setDiagnosis] = useState<DiagnosisResult>(); const [exercises, setExercises] = useState<ExerciseResult[]>([]);
  const [aiStatus, setAiStatus] = useState<AIStatus>();
  const loadClasses = useCallback(async () => { const data = await api.listClassrooms(); setClasses(data); setClassId((old) => data.some((c) => c.id === old) ? old : data[0]?.id ?? ''); }, []);
  const loadGraph = useCallback(async (id: string) => { if (!id) { setGraph(emptyGraph); return; } const data = await api.classGraph(id); setGraph(data); setSelected((old) => data.nodes.find((n) => n.id === old?.id) ?? data.nodes[0]); }, []);
  useEffect(() => { void run(loadClasses); }, [loadClasses, run]); useEffect(() => { void run(() => loadGraph(classId)); }, [classId, loadGraph, run]); useEffect(() => { void run(async () => setAiStatus(await api.aiStatus())); }, [run]);
  const classroom = classes.find((item) => item.id === classId); const mastered = graph.nodes.filter((n) => n.mastered).length;
  const pathEdgeIds = useMemo(() => path?.path_edges.map((edge) => edge.id) ?? emptyPathEdgeIds, [path]);
  return <><PageHeading title="学习空间" description="这里只显示你已加入且正在开课的教学班。" actions={<div className="join-form"><input placeholder="输入班级码" value={joinCode} onChange={(e) => setJoinCode(e.target.value.toUpperCase())} /><button className="secondary" onClick={() => run(async () => { await api.joinClass(joinCode); setJoinCode(''); await loadClasses(); }, '已加入班级。')}><Plus size={16} />加入班级</button></div>} />{!classes.length ? <EmptyState icon={School} title="还没有加入教学班" text="向任课教师获取班级码，加入后即可查看课程图谱。" /> : <><div className="student-toolbar"><select value={classId} onChange={(e) => setClassId(e.target.value)}>{classes.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.course_name}</option>)}</select><span>{classroom?.semester}</span><b>{mastered}/{graph.nodes.length} 已掌握</b><span className={`ai-mode compact ${aiStatus?.configured ? 'online' : 'offline'}`}>{aiStatus?.configured ? 'DeepSeek 真 AI' : '离线演示'}</span></div><div className="learning-grid"><section className="surface graph-workspace"><GraphView graph={graph} selectedNodeId={selected?.id} pathEdgeIds={pathEdgeIds} onSelectNode={setSelected} /></section><aside className="learning-side"><section className="surface"><h3>知识点详情</h3>{selected ? <><span className="node-type">{selected.type}</span><h2>{selected.name}</h2><p>{selected.definition}</p><small>{selected.example}</small><button className={selected.mastered ? 'secondary wide' : 'primary wide'} onClick={() => run(async () => { await api.classProgress(classId, selected.id, !selected.mastered); await loadGraph(classId); }, selected.mastered ? '已取消掌握标记。' : '学习进度已更新。')}>{selected.mastered ? '取消掌握' : '标记为已掌握'}</button></> : <p>点击图谱节点查看内容。</p>}</section><section className="surface"><h3><Route size={17} />个性化学习建议</h3><div className="button-row"><button className="secondary" onClick={() => run(async () => setDiagnosis(await api.diagnosis(classId)))}>学习诊断</button><button className="secondary" onClick={() => run(async () => setPath(await api.classPath(classId)))}>推荐路径</button><button className="secondary" onClick={() => run(async () => setExercises(await api.exercises(classId)))}>生成练习</button></div>{diagnosis && <div className="diagnosis"><b>掌握率 {diagnosis.mastery_rate}% · {diagnosis.mode}</b><p>{diagnosis.ai_analysis}</p>{diagnosis.suggestions.map((s) => <p key={s}>{s}</p>)}</div>}{path?.ai_summary && <div className="diagnosis"><b>{path.mode}</b><p>{path.ai_summary}</p></div>}{path?.recommendations.map((item) => <div className="path-item" key={item.node.id}><b>{item.node.name}</b><span>{item.reason}</span></div>)}{exercises.map((item) => <details className="exercise" key={`${item.node_id}-${item.question_type}`}><summary>{item.question_type} · {item.difficulty}｜{item.question}</summary><p>{item.answer}</p><small>{item.explanation}</small>{item.sources.map((source, index) => <small key={`${source.source}-${index}`}>来源：{source.source}</small>)}</details>)}</section><section className="surface"><h3><Bot size={17} />可溯源问答</h3><textarea value={question} onChange={(e) => setQuestion(e.target.value)} /><button className="primary" onClick={() => run(async () => setAnswer(await api.classQa(classId, question)), '已基于课程证据生成回答。')}><Send size={15} />提问</button>{answer && <div className="answer"><p>{answer.answer}</p><div className="answer-meta"><span>{answer.mode}</span><span>置信度 {answer.confidence}</span></div>{answer.evidence.map((e, index) => <details key={`${e.source}-${index}`}><summary>[{index + 1}] {e.source}</summary><small>{e.excerpt}</small></details>)}</div>}</section></aside></div></>}</>;
}

function AdminOverview({ run }: RunProps) {
  const [stats, setStats] = useState<DashboardStats>(); useEffect(() => { void run(async () => setStats(await api.dashboard())); }, [run]);
  return <><PageHeading title="学校运行概览" description="独立管理员控制台汇总用户、课程、班级、审核和反馈状态。" /><MetricGrid items={[['全部用户', stats?.users ?? 0], ['教师', stats?.teachers ?? 0], ['学生', stats?.students ?? 0], ['待审教师', stats?.pending_teachers ?? 0], ['课程', stats?.courses ?? 0], ['教学班', stats?.classrooms ?? 0], ['待处理工单', stats?.open_tickets ?? 0]]} /><section className="surface admin-callout"><ShieldCheck size={30} /><div><h3>管理边界已独立</h3><p>管理员可以审核教师、查看全校数据、批量导入成员、处理工单并追踪审计日志。</p></div></section></>;
}

function AdminUsers({ run }: RunProps) {
  const [users, setUsers] = useState<User[]>([]); const [query, setQuery] = useState(''); const load = useCallback(() => run(async () => setUsers(await api.adminUsers('', '', query))), [query, run]); useEffect(() => { void load(); }, [load]);
  const pending = users.filter((u) => u.role === 'teacher' && u.account_status === 'pending');
  return <><PageHeading title="用户与教师审核" description="学生注册直接激活；教师申请由管理员审核后才能开课。" actions={<div className="search-box"><Search size={16} /><input placeholder="姓名、用户名或学号" value={query} onChange={(e) => setQuery(e.target.value)} /></div>} />{pending.length > 0 && <section className="surface"><h3>待审核教师</h3>{pending.map((teacher) => <div className="approval" key={teacher.id}><div><b>{teacher.name}</b><span>{teacher.department} · {teacher.title} · {teacher.email}</span></div><button className="primary" onClick={() => run(async () => { await api.reviewTeacher(teacher.id, 'approve'); await load(); }, '教师申请已通过。')}><Check size={15} />通过</button><button className="danger" onClick={() => { const reason = window.prompt('请输入驳回原因'); if (reason) void run(async () => { await api.reviewTeacher(teacher.id, 'reject', reason); await load(); }, '申请已驳回。'); }}><X size={15} />驳回</button></div>)}</section>}<section className="surface"><h3>全部用户</h3><div className="table-wrap"><table><thead><tr><th>用户名/学号</th><th>姓名</th><th>角色</th><th>院系</th><th>账号状态</th></tr></thead><tbody>{users.map((account) => <tr key={account.id}><td>{account.student_no || account.username}</td><td>{account.name}</td><td>{roleName(account.role)}</td><td>{account.department || '-'}</td><td><select value={account.account_status} onChange={(event) => run(async () => { await api.adminUpdateUser(account.id, { name: account.name, email: account.email, phone: account.phone, account_status: event.target.value, department: account.department, title: account.title, student_no: account.student_no }); await load(); }, '账号状态已更新。')}><option value="active">正常</option><option value="pending">待审核</option><option value="rejected">已驳回</option><option value="disabled">已禁用</option></select></td></tr>)}</tbody></table></div></section></>;
}

function AdminResources({ mode, run }: RunProps & { mode: 'classes' | 'courses' }) {
  const [classes, setClasses] = useState<Classroom[]>([]); const [courses, setCourses] = useState<Course[]>([]); const [teachers, setTeachers] = useState<User[]>([]);
  const load = useCallback(async () => { const [classData, courseData, teacherData] = await Promise.all([api.listClassrooms(), api.listCourses(), api.adminUsers('teacher', 'active')]); setClasses(classData); setCourses(courseData); setTeachers(teacherData); }, []);
  useEffect(() => { void run(load); }, [load, run]);
  return <><PageHeading title={mode === 'classes' ? '全部教学班' : '全部课程'} description="查看并调整学校范围内的教学资源、归属教师和运行状态。" /><section className="surface"><div className="table-wrap"><table><thead><tr>{(mode === 'classes' ? ['班级', '课程', '主教师', '学期', '人数', '状态'] : ['课程', '主教师', '班级数', '学生数', '图谱规模', '状态']).map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{mode === 'classes' ? classes.map((classroom) => <tr key={classroom.id}><td>{classroom.name}</td><td>{classroom.course_name}</td><td><select value={classroom.primary_teacher_id} onChange={(event) => run(async () => { await api.reassignPrimaryTeacher(classroom.id, event.target.value); await load(); }, '班级主教师已调整。')}>{teachers.map((teacher) => <option key={teacher.id} value={teacher.id}>{teacher.name}</option>)}</select></td><td>{classroom.semester}</td><td>{classroom.student_count}</td><td><select value={classroom.status} onChange={(event) => run(async () => { await api.updateClassroom(classroom.id, { name: classroom.name, semester: classroom.semester, join_enabled: classroom.join_enabled, status: event.target.value }); await load(); }, '班级状态已更新。')}><option value="draft">筹备中</option><option value="active">开课中</option><option value="closed">已结课</option></select></td></tr>) : courses.map((course) => <tr key={course.id}><td>{course.name}</td><td>{course.owner_name}</td><td>{course.classroom_count}</td><td>{course.student_count}</td><td>{course.stats.nodes}/{course.stats.edges}</td><td><select value={course.status} onChange={(event) => run(async () => { await api.updateCourse(course.id, { name: course.name, description: course.description, status: event.target.value }); await load(); }, '课程状态已更新。')}><option value="draft">草稿</option><option value="published">已发布</option><option value="archived">已归档</option></select></td></tr>)}</tbody></table></div></section></>;
}

function TicketCenter({ user, run }: RunProps & { user: User }) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Ticket>();
  const [form, setForm] = useState({ category: 'system', severity: 'medium', subject: '', description: '' });
  const [reply, setReply] = useState('');
  const load = useCallback(async () => {
    const data = await api.tickets();
    setTickets(data);
    if (selected) setSelected(data.find((ticket) => ticket.id === selected.id));
  }, [selected]);
  useEffect(() => { void run(load); }, [load, run]);
  return <>
    <PageHeading title="反馈工单" description={user.role === 'admin' ? '处理全校用户提交的系统、课程和账号问题。' : '遇到突发问题时向管理员提交反馈并跟踪处理进度。'} />
    <div className="ticket-grid">
      <section className="surface">
        <h3>{user.role === 'admin' ? '全部工单' : '我的工单'}</h3>
        {tickets.map((ticket) => <button className={`ticket-item ${selected?.id === ticket.id ? 'active' : ''}`} key={ticket.id} onClick={() => run(async () => setSelected(await api.ticket(ticket.id)))}><span className={`severity ${ticket.severity}`} /><div><b>{ticket.subject}</b><small>{ticket.creator_name} · {ticket.status}</small></div></button>)}
      </section>
      <section className="surface">
        {selected ? <>
          <div className="surface-title"><div><h3>{selected.subject}</h3><p>{selected.description}</p></div><span className="badge">{selected.status}</span></div>
          {selected.attachments.length > 0 && <div className="ticket-attachments">{selected.attachments.map((item) => <span key={item.id}><FileText size={14} />{item.filename}</span>)}</div>}
          <div className="messages">{selected.messages.map((message) => <div className={message.author_id === user.id ? 'mine' : ''} key={message.id}><b>{message.author_name}</b><p>{message.content}</p><small>{message.created_at}</small></div>)}</div>
          <div className="reply"><textarea placeholder="输入回复" value={reply} onChange={(event) => setReply(event.target.value)} /><button className="primary" onClick={() => run(async () => { setSelected(await api.replyTicket(selected.id, reply)); setReply(''); await load(); }, '回复已发送。')}><Send size={15} />回复</button>{user.role === 'admin' && <select value={selected.status} onChange={(event) => run(async () => { setSelected(await api.updateTicket(selected.id, { status: event.target.value, assigned_admin_id: user.id })); await load(); }, '工单状态已更新。')}><option value="open">待处理</option><option value="in_progress">处理中</option><option value="waiting_user">等待用户</option><option value="resolved">已解决</option><option value="closed">已关闭</option></select>}</div>
          <label className="secondary file-button"><Upload size={15} />添加截图或 PDF<input type="file" accept="image/*,.pdf" onChange={(event) => { const file = event.target.files?.[0]; if (file) void run(async () => setSelected(await api.addTicketAttachment(selected.id, file)), '附件已上传。'); }} /></label>
        </> : <>
          <h3>提交新反馈</h3>
          <label>问题分类<select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}><option value="system">系统问题</option><option value="course">课程问题</option><option value="graph">图谱问题</option><option value="account">账号问题</option><option value="other">其他</option></select></label>
          <label>紧急程度<select value={form.severity} onChange={(event) => setForm({ ...form, severity: event.target.value })}><option value="low">低</option><option value="medium">一般</option><option value="high">高</option><option value="urgent">紧急</option></select></label>
          <label>标题<input value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} /></label>
          <label>问题描述<textarea rows={6} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          <button className="primary" onClick={() => run(async () => { const ticket = await api.createTicket(form); setForm({ ...form, subject: '', description: '' }); setSelected(ticket); await load(); }, '反馈已提交。')}><LifeBuoy size={16} />提交工单</button>
        </>}
      </section>
    </div>
  </>;
}

function ProfileCenter({ user, onUser, run }: RunProps & { user: User; onUser: (user: User) => void }) {
  const [form, setForm] = useState({ name: user.name, email: user.email, phone: user.phone, title: user.title });
  const [password, setPassword] = useState({ current: '', next: '' });
  return <>
    <PageHeading title="个人中心" description="维护头像、联系方式与登录密码；关键身份字段由管理员管理。" />
    <div className="profile-grid">
      <section className="surface profile-card">
        {user.avatar_url ? <div className="avatar-large">{user.name.slice(0, 1)}</div> : <div className="avatar-large">{user.name.slice(0, 1)}</div>}
        <label className="secondary file-button avatar-upload"><Upload size={15} />更换头像<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void run(async () => onUser(await api.uploadAvatar(file)), '头像已更新。'); }} /></label>
        <h2>{user.name}</h2><p>{roleName(user.role)} · {user.account_status}</p>
        <dl><dt>用户名</dt><dd>{user.username}</dd>{user.student_no && <><dt>学号</dt><dd>{user.student_no}</dd></>}<dt>学校</dt><dd>{user.organization}</dd>{user.department && <><dt>院系</dt><dd>{user.department}</dd></>}</dl>
      </section>
      <section className="surface">
        <h3>个人资料</h3>
        <label>姓名<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
        <label>邮箱<input value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
        <label>手机号<input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
        {user.role === 'teacher' && <label>职称<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>}
        <button className="primary" onClick={() => run(async () => onUser(await api.updateProfile(form)), '个人资料已保存。')}><Save size={15} />保存资料</button>
        <hr /><h3>修改密码</h3>
        {user.must_change_password && <p className="warning-text">首次登录必须修改临时密码后才能进入课程。</p>}
        <label>当前密码<input type="password" value={password.current} onChange={(event) => setPassword({ ...password, current: event.target.value })} /></label>
        <label>新密码<input type="password" value={password.next} onChange={(event) => setPassword({ ...password, next: event.target.value })} /></label>
        <button className="secondary" onClick={() => run(async () => { await api.updatePassword(password.current, password.next); onUser(await api.me()); setPassword({ current: '', next: '' }); }, '密码已修改。')}><Settings size={15} />更新密码</button>
      </section>
    </div>
  </>;
}

function PendingReview({ user }: { user: User }) { return <EmptyState icon={ShieldCheck} title={user.account_status === 'rejected' ? '教师申请需要补充' : '教师申请审核中'} text={user.account_status === 'rejected' ? `驳回原因：${user.rejection_reason || '请联系管理员了解详情'}` : '管理员审核通过后，你将可以开设课程和创建教学班。审核期间仍可修改个人资料或提交反馈。'} />; }
function AuditLog({ run }: RunProps) { const [logs, setLogs] = useState<Array<Record<string, string>>>([]); useEffect(() => { void run(async () => setLogs(await api.auditLogs())); }, [run]); return <><PageHeading title="审计日志" description="追踪审核、导入、图谱版本和关键管理操作。" /><section className="surface"><DataTable headers={['时间', '操作人', '动作', '对象', '详情']} rows={logs.map((l) => [l.created_at, l.actor_name, l.action, `${l.target_type}:${l.target_id}`, l.detail_json])} /></section></>; }

function PageHeading({ title, description, actions }: { title: string; description: string; actions?: React.ReactNode }) { return <header className="page-heading"><div><h2>{title}</h2><p>{description}</p></div>{actions}</header>; }
function MetricGrid({ items, compact = false }: { items: Array<[string, string | number]>; compact?: boolean }) { return <div className={`metric-grid ${compact ? 'compact' : ''}`}>{items.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>; }
function DataTable({ headers, rows }: { headers: string[]; rows: Array<Array<string | number>> }) { return <div className="table-wrap"><table><thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={`${i}-${j}`}>{cell}</td>)}</tr>)}</tbody></table>{!rows.length && <p className="muted table-empty">暂无数据</p>}</div>; }
function EmptyState({ icon: Icon, title, text }: { icon: typeof School; title: string; text: string }) { return <section className="surface empty-state"><Icon size={40} /><h2>{title}</h2><p>{text}</p></section>; }
function roleName(role: User['role']) { return role === 'admin' ? '管理员' : role === 'teacher' ? '教师' : '学生'; }
function defaultView(user: User): View { return 'home'; }
function nodeName(graph: KnowledgeGraph, id: string) { return graph.nodes.find((node) => node.id === id)?.name ?? id; }
interface RunProps { run: (action: () => Promise<void>, success?: string) => Promise<void> }
