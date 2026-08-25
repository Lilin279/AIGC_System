# 系统使用说明

## 安装部署

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

## 操作流程

1. 打开 http://127.0.0.1:5173。
2. 顶部选择课程。
3. 教师端上传 TXT / Markdown 文档，等待抽取完成。
4. 点击图谱节点查看知识点详情。
5. 教师端可新增演示节点，体现人工修正能力。
6. 学生端标记已掌握节点。
7. 点击“生成下一步路径”查看推荐。
8. 在智能问答中输入问题，查看回答和引用节点。

## 常见问题

- PowerShell 无法运行 npm：使用 `npm.cmd install` 和 `npm.cmd run dev`。
- 后端提示缺少 FastAPI：进入 `backend` 后执行 pip 安装命令。
- 上传 PDF/DOCX 失败：第一版仅支持 TXT / Markdown，PDF/DOCX 为后续扩展。
- 想恢复初始数据：启动后端后运行 `scripts/reset-demo.ps1`。
