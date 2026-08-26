# AIGC 课程知识图谱学习导航系统

面向“基于 AIGC 的课程知识图谱智能构建与学习导航系统”赛题的客户演示版 MVP。项目提供 React + FastAPI 前后端分离系统，覆盖登录、开课、资料管理、图谱编辑、学习导航、智能问答，并配套需求调研、目标分析、技术方案、竞赛材料清单和测试模板。

## 项目结构

```text
D:\AIGC
├── backend/          # FastAPI 后端 API
├── frontend/         # React + Vite + TypeScript 前端
├── sample_data/      # 示例课程、示例文档、预置图谱
├── docs/             # 竞赛前置文档与测试模板
├── scripts/          # Windows 启动与重置脚本
├── 赛题.txt
└── 服务外包竞赛要点.txt
```

## 快速启动

```powershell
cd D:\AIGC\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

另开一个 PowerShell：

```powershell
cd D:\AIGC\frontend
npm.cmd install
npm.cmd run dev
```

访问：

- 前端：http://127.0.0.1:5173
- 后端文档：http://127.0.0.1:8000/docs

## 演示流程

1. 进入教师端，选择课程。
2. 上传 `sample_data/documents/` 中的 TXT 或 Markdown 示例资料。
3. 教师端可开设新课程、保存课程信息、删除课程。
4. 上传 PDF、Word、PPT、TXT 或 Markdown 资料，系统自动执行 Mock AIGC 知识抽取。
5. 在“知识点编辑”中新增、编辑、删除知识点。
6. 在“关系编辑”中选择源知识点、目标知识点和关系类型，完成知识点链接。
7. 使用学生角色登录，标记已掌握知识点，生成学习路径推荐。
8. 输入问题，查看基于课程图谱的离线 RAG 演示回答和引用节点。

## 原型说明

当前版本默认不依赖真实大模型 API 和 Neo4j，确保普通电脑可直接运行。后续可以在 `backend/app/services/extractor.py` 和 `backend/app/services/qa.py` 中替换为 DeepSeek / 通义千问 + GraphRAG 流程，并在 `backend/app/storage.py` 增加 Neo4j 适配实现。
