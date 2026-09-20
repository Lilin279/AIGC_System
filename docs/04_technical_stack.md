# 技术栈选择

## 前端

- React：组件化开发教师端、学生端和图谱面板。
- Vite：轻量开发服务器和构建工具。
- TypeScript：提高接口和图谱数据结构可维护性。
- AntV G6：负责知识图谱渲染、缩放、拖拽和节点交互。
- lucide-react：提供清晰的功能图标。

## 后端

- FastAPI：提供课程、文档、图谱、问答和推荐 API，并自带 Swagger 文档。
- Pydantic：定义 Course、KnowledgeNode、KnowledgeEdge 等数据模型。
- JSON 本地存储：第一版降低部署门槛，保证可演示。

## 扩展路线

- LLM：DeepSeek / 通义千问用于实体识别、关系抽取和问答生成。
- Neo4j：用于生产级图谱存储、Cypher 查询和图遍历。
- GraphRAG：中文 N-gram/FTS5/BM25、BGE 中文 Embedding、Qdrant、Neo4j 一至两跳扩展和 BGE Cross-Encoder 重排序。
