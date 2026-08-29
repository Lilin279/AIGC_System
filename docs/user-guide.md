# 系统使用说明

> 本文已更新到 P1/P2 客户化版本。系统入口按教师、学生和管理员角色显示独立导航。

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
2. 使用账号登录；教师 `teacher / Teacher123!`，学生 `student / Student123!`，管理员 `admin / Admin123!`。
3. 教师端可开设新课程、保存课程信息、删除课程。
4. 教师端上传 PDF、Word、PPT、TXT 或 Markdown 资料，启动抽取任务并等待候选图谱；候选版本必须由教师审核后应用。
5. 点击图谱节点后，在“知识点编辑”中修改名称、类型、定义和示例。
6. 在“关系编辑”中选择源知识点、目标知识点和关系类型，新增或修改知识点链接。
7. 学生也可在登录页自行注册；登录后只能看到已发布课程，并可标记个人已掌握节点。
8. 点击“生成下一步路径”查看推荐；排序来自前置关系与掌握状态，AI 只负责解释。
9. 在智能问答中输入问题，查看课件名、页码、引用片段、知识点和置信提示。
10. 点击练习生成基础题、应用题和易错题，在线与离线模式会明确标记。

## 常见问题

- PowerShell 无法运行 npm：使用 `npm.cmd install` 和 `npm.cmd run dev`。
- 后端提示缺少 FastAPI：进入 `backend` 后执行 pip 安装命令。
- PDF 解析为空：部分扫描版 PDF 不包含可提取文本，需要 OCR 扩展。
- 想恢复初始数据：启动后端后运行 `scripts/reset-demo.ps1`。
- 登录后刷新页面仍会保持会话；点击右上角退出按钮会立即使当前令牌失效。
- 课程无法发布：请确认图谱中至少有 3 个知识点和 1 条知识关系。

### 为什么上传后学生没有立即看到新图谱？

抽取结果先进入候选版本。教师必须在课程工作室审核并确认应用，学生才会看到更新。

### 删除错误课件时图谱会怎样处理？

删除弹窗默认选中“同步撤销”。系统删除仅由该课件产生且未人工修订的节点和关系；多课件共享内容和手工修订继续保留。关闭同步撤销后，图谱保留并标记来源不完整。

### 学生为什么看不到某门已发布课程？

学生只看得到自己已加入、处于开课状态教学班所关联的课程。请使用班级码加入，或由教师/管理员导入。

### 如何启用扫描 PDF？

执行 `.\.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt` 安装可选 OCR 组件。普通文本 PDF 不需要安装。

### 如何启用真实 DeepSeek？

复制根目录 `.env.example` 为 `.env`，填写 `DEEPSEEK_API_KEY` 后重启后端。登录后可访问 `/api/ai/status` 检查状态；接口永远不会返回 Key。未配置或调用失败时界面明确显示离线演示/降级模式，不会伪装成真实调用。

### 为什么真实 AI 抽取后仍然需要审核？

DeepSeek 输出会经过 Pydantic 结构校验、实体引用校验和来源核对，但不能替代教师判断。少于 20 个知识点、关系类型不足或来源覆盖过低时，候选版本会显示质量提醒且不会自动应用。
