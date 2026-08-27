# AIGC 课程知识图谱学习导航系统

面向“基于 AIGC 的课程知识图谱智能构建与学习导航系统”赛题的可运行客户版 MVP。项目提供 React + FastAPI 前后端分离系统，使用 SQLite 持久化账号、课程、资料元数据、知识图谱和个人学习进度，覆盖登录、开课、资料管理、课程发布、图谱编辑、学习导航与智能问答。

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

内置账号（仅用于本地演示）：

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 教师 | `teacher` | `Teacher123!` |
| 学生 | `student` | `Student123!` |
| 管理员 | `admin` | `Admin123!` |

1. 使用教师账号登录，开设课程并上传 PDF、Word、PPT、TXT 或 Markdown 资料。
2. 在“知识点编辑”和“关系编辑”中修正图谱，至少保留 3 个知识点和 1 条关系后发布课程。
3. 使用学生账号登录，只能看到已发布课程；标记掌握状态并生成学习路径。
4. 刷新页面验证会话与个人进度仍然保留，再使用智能问答查看回答和引用节点。

## 原型说明

当前版本默认不依赖真实大模型 API 和 Neo4j，确保普通电脑可直接运行。账号密码使用 PBKDF2 加盐哈希，会话令牌可过期和注销；教师课程归属、角色权限与学生个人进度均在服务端校验。下一阶段可在 `backend/app/services/extractor.py` 和 `backend/app/services/qa.py` 中接入 DeepSeek / 通义千问 + GraphRAG，并增加 Neo4j 图存储适配。
