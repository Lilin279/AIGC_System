# 数据库设计

## 三层主模型

- `courses`：课程内容、发布状态、主教师、当前确认图谱版本。
- `classrooms`：教学班名称、学期、班级码、状态、关联课程与主教师。
- `class_teachers`、`enrollments`：协作教师授权和学生入班关系。

## 图谱生命周期

- `documents`、`document_chunks`：课件元数据、正文分片、页码和存储路径。
- `extraction_jobs`：可恢复的抽取任务状态和候选版本。
- `graph_versions`：候选、活动、驳回、历史版本的完整 JSON 快照。
- `nodes`、`edges`：当前确认图谱。
- `node_sources`、`edge_sources`：课件来源、共享来源、手工来源和人工覆盖标记。

## 教学与服务

- `class_learning_progress`：按用户、教学班、知识点隔离掌握状态。
- `teacher_applications`：教师申请、审核人、审核时间和原因。
- `import_jobs`：批量导入预检数据与提交状态。
- `tickets`、`ticket_messages`、`ticket_attachments`：反馈工单全流程。
- `notifications`、`audit_logs`：站内通知和关键写操作审计。

所有外键连接均启用 SQLite foreign keys；高频检索字段已建立课程、班级、成员、任务、版本、工单和日志索引。迁移器通过 `schema_migrations` 与幂等列检查兼容 P0 数据。
