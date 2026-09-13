# Neo4j 联调与验收记录

## 验收结论

2026-09-06 在项目本地运行环境完成真实 Neo4j HTTP Transaction API 联调。应用成功读取根目录 `.env`，通过 Basic Auth 完成认证，并执行 Cypher 查询、两门课程全量同步和逐课程一致性校验。

本次结果：

| 项目 | 结果 |
|---|---:|
| 已同步课程 | 2 |
| 同步成功 | 2 |
| 同步失败 | 0 |
| CourseGraph AI 受管节点 | 40 |
| CourseGraph AI 受管关系 | 40 |
| `python_intro` 前置关系查询 | 9 |
| `python_intro` 两跳邻居查询 | 成功，按测试上限返回 5 条 |
| 教师视角端到端学习路径 | `neo4j-rule`，返回 6 个推荐项 |
| 教师视角 GraphRAG 检索 | 返回 4 条 Neo4j 邻居证据 |

两个课程 `python_intro`、`database_systems` 的 `consistent` 均为 `true`。校验维度包括节点数、关系数和 `active_version_id`。

## 产品内验收方式

1. 启动后端并以教师账号登录。
2. 进入“课程工作室”，确认工具栏显示“Neo4j 已连接”。
3. 选择课程并点击“同步图谱”。
4. 页面提示“当前课程已同步并通过 Neo4j 一致性校验”。
5. 学生生成推荐路径，返回模式包含 `+neo4j`。
6. 学生提出与课程知识点相关的问题，证据中出现“Neo4j 图谱邻居扩展”。

管理员也可调用 `POST /api/admin/integrations/neo4j/sync` 对全部课程执行同步。`GET /api/integrations` 会执行真实认证与 Cypher 查询，不会返回 URL、用户名或密码。

## 故障降级与恢复

- Neo4j 请求对网络错误、HTTP 429 和 5xx 最多重试三次。
- 同步状态、尝试次数、SQLite/Neo4j 计数和错误信息保存在 `neo4j_sync_state`。
- 同步失败不会回滚 SQLite 正式图谱，学习路径和 GraphRAG 自动改用 SQLite。
- 服务重启后后台补偿未同步、版本变化或计数变化的课程。
- 图谱审核、历史恢复、手工节点/关系编辑和课件回滚都会触发同步。

## 安全说明

Neo4j 请求禁用系统 HTTP 代理，避免本机 `localhost` 被代理转发，也避免图数据库凭据进入代理链路。验收命令、接口返回、日志和本文档均不包含 Neo4j 密码。
