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
2. 使用教师、学生或管理员角色进入系统。
3. 教师端可开设新课程、保存课程信息、删除课程。
4. 教师端上传 PDF、Word、PPT、TXT 或 Markdown 资料，等待解析和图谱生成。
5. 点击图谱节点后，在“知识点编辑”中修改名称、类型、定义和示例。
6. 在“关系编辑”中选择源知识点、目标知识点和关系类型，新增或修改知识点链接。
7. 使用学生角色登录，标记已掌握节点。
8. 点击“生成下一步路径”查看推荐。
9. 在智能问答中输入问题，查看回答和引用节点。

## 常见问题

- PowerShell 无法运行 npm：使用 `npm.cmd install` 和 `npm.cmd run dev`。
- 后端提示缺少 FastAPI：进入 `backend` 后执行 pip 安装命令。
- PDF 解析为空：部分扫描版 PDF 不包含可提取文本，需要 OCR 扩展。
- 想恢复初始数据：启动后端后运行 `scripts/reset-demo.ps1`。
