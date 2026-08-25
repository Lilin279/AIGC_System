# AIGC 课程知识图谱学习导航系统

服务外包竞赛原型项目，面向“基于 AIGC 的课程知识图谱智能构建与学习导航系统”赛题。项目提供可运行的 React + FastAPI 前后端分离原型，并配套需求调研、目标分析、技术方案、竞赛材料清单和测试模板。

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
3. 系统自动执行 Mock AIGC 知识抽取，生成不少于 20 个知识点和三类关系。
4. 在图谱中点击节点，查看定义、示例和资源。
5. 切换学生端，标记已掌握知识点。
6. 生成学习路径推荐，观察前置关系高亮。
7. 输入问题，查看基于课程图谱的离线 RAG 演示回答和引用节点。

## 原型说明

第一版默认不依赖真实大模型 API 和 Neo4j，确保普通电脑可直接运行。后续可以在 `backend/app/services/extractor.py` 和 `backend/app/services/qa.py` 中替换为 DeepSeek / 通义千问 + GraphRAG 流程，并在 `backend/app/storage.py` 增加 Neo4j 适配实现。
