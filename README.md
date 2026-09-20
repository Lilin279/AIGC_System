# CourseGraph AI 课程知识图谱教学平台

面向高校和职业院校的课程知识图谱构建、教学班管理与个性化学习系统。当前 P1/P2 版本已经形成“课程内容 - 教学班级 - 师生关系”闭环，并以可溯源 GraphRAG 作为竞赛主创新。

## 已实现能力

- 学生注册直接激活；教师注册后由管理员审核，待审账号只能进入审核状态、个人中心和工单；注册均需填写学校名称。
- 课程与教学班分离；一门课程可关联多个班，学生只能看到自己加入的开课班级。
- PDF、DOCX、PPTX、TXT、Markdown 解析；扫描 PDF 可选安装 OCR 组件。
- 抽取任务持久化；本地规则抽取与 DeepSeek 真实抽取明确区分。
- AIGC 先生成候选图谱，教师审核后才发布；支持版本恢复、质量评分和操作审计。
- 删除课件前预览影响；默认选择性回滚单一来源节点/关系，保留共享来源和人工修订。
- 节点与关系完整增删改，所有手工修订进入版本与来源记录。
- 按学生和班级隔离学习进度，路径顺序由前置关系确定，DeepSeek 基于证据生成诊断解释和练习，练习支持自选题型（基础题/应用题/易错题）与数量。
- SQLite FTS5 中文 2/3-gram、BM25、中文 Embedding、Qdrant 向量检索、Neo4j 邻居扩展和 Cross-Encoder 重排序组成可降级的多通道 GraphRAG。
- 管理员独立控制台：教师审核、全校用户/班级/课程、两步批量导入、工单和审计日志。
- 个人资料、头像、密码、工单附件、站内通知；导入账号首次登录强制改密。
- SQLite 保存业务数据；Neo4j 保存已确认图谱并实际参与前置关系查询和 GraphRAG 两跳邻居召回，连接失败自动降级。

## 线上演示

部署于腾讯云轻量服务器（2核2G，Docker Compose + Neo4j + 真实 DeepSeek）：<http://159.75.42.159/>

生产环境仅对外暴露 80 端口，后端与 Neo4j 仅本机可访问；数据保存在 Docker 卷中，更新代码不影响线上数据。

## 本地启动

后端：

```powershell
cd D:\AIGC\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd D:\AIGC\frontend
npm.cmd install
npm.cmd run dev
```

访问前端 `http://127.0.0.1:5173`，接口文档 `http://127.0.0.1:8000/docs`。

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

数据保存在 `coursegraph_data` 卷。启用 Neo4j 时，在 `.env` 设置 `NEO4J_HTTP_URL=http://neo4j:7474`，然后运行：

```powershell
docker compose --profile neo4j up --build
```

## Neo4j 图数据库

本地启动后端时，`NEO4J_HTTP_URL` 应指向宿主机可访问的 Neo4j HTTP 地址（通常为 `http://localhost:7474`）；后端运行在 Compose 中时应使用 `http://neo4j:7474`。可通过以下接口验收：

- `GET /api/integrations`：执行真实认证和 Cypher 查询，返回连接、节点/关系计数和同步状态。
- `POST /api/courses/{course_id}/graph/sync`：教师同步当前课程，并核对 SQLite/Neo4j 的节点数、关系数和版本。
- `POST /api/admin/integrations/neo4j/sync`：管理员全量同步所有课程。

审核、恢复、手工编辑和课件回滚都会自动同步。失败记录保存在 SQLite，服务重启后自动补偿；学习路径返回模式含 `+neo4j` 时表示前置关系来自 Neo4j，问答证据中的“Neo4j 图谱邻居扩展”表示已使用两跳图召回。

## DeepSeek

不配置 Key 时，页面和接口会明确显示“本地规则模式”。真实联调时只需在 `.env` 或本机环境变量中设置：

```text
DEEPSEEK_API_KEY=你的Key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

模型和 JSON Output 参数依据 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [JSON Output](https://api-docs.deepseek.com/guides/json_mode/) 官方文档。

系统不会记录 Key、提示正文或课件内容；`ai_usage_logs` 仅保存模型、能力、Token、耗时与状态。真实联调和 24 题问答验收见 `docs/13_ai_integration_and_acceptance.md`。

## 多通道混合 GraphRAG

设置 `HYBRID_RAG_ENABLED=true` 后，系统使用 `BAAI/bge-small-zh-v1.5` 生成中文向量，使用 Qdrant 本地持久化向量库，并通过 `BAAI/bge-reranker-base` 对候选证据重排序。首次使用需要联网下载模型；模型或向量库异常时自动回退到 BM25 与 Neo4j 图检索。

检索结果同时返回 BM25、向量、图谱、来源、融合和重排分数。完整配置、评分公式与评测方式见 `docs/14_hybrid_graphrag.md`；知识抽取、问答、检索消融、推荐路径和并发性能的实测数据见 `docs/15_evaluation_report.md`。

## 自动化测试

```powershell
cd D:\AIGC\backend
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试覆盖角色与班级隔离、课件回滚、候选版本、中文 BM25、课程证据隔离、AI JSON 校验及 429/5xx/超时降级。图谱渲染保持当前稳定版本，仅做回归检查。

## 演示账号

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `Admin123!` |
| 教师 | `teacher` | `Teacher123!` |
| 学生 | `student` | `Student123!` |

学生导入模板位于 `sample_data/student-import-template.csv`。详细操作和交付边界见 `docs/user-guide.md` 与 `docs/12_p1_p2_delivery.md`。
