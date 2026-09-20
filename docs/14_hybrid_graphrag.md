# 多通道混合 GraphRAG

## 实现范围

系统在原有中文 FTS5/BM25 和 Neo4j 图谱扩展基础上增加两个检索阶段：

- 使用 `BAAI/bge-small-zh-v1.5` 生成 512 维中文语义向量。
- 使用 Qdrant 保存文本块向量。默认采用本地持久化模式，也可连接独立 Qdrant 服务。
- 使用 `BAAI/bge-reranker-base` 对初步召回证据执行 Cross-Encoder 重排序。
- Embedding、向量库或重排序器失败时自动降级，不影响原 BM25 和图谱问答。

模型只在首次向量检索时延迟加载。启用前需要预留模型下载时间和存储空间。

## 检索与融合

候选证据来自四类信号：

1. `S_bm25`：中文二元、三元词组的 FTS5/BM25 相关性。
2. `S_vector`：问题向量与文本块向量的余弦相似度。
3. `S_graph`：直接知识点匹配与 Neo4j 一至两跳邻居距离。
4. `S_source`：页码完整度、来源置信度和人工修订状态。

各分数归一化到 `[0, 1]` 后计算：

```text
S_hybrid = α S_bm25 + β S_vector + γ S_graph + δ S_source
```

默认权重为 `α=0.30`、`β=0.30`、`γ=0.25`、`δ=0.15`。Cross-Encoder 将问题与每条候选证据联合编码，系统再计算：

```text
S_final = (1 - λ) S_hybrid + λ S_reranker
```

默认 `λ=0.35`。回答接口返回各通道分数、融合分数、重排分数和最终名次，便于复核和消融实验。

## 配置

在 `.env` 中设置：

```text
HYBRID_RAG_ENABLED=true
HYBRID_RAG_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
HYBRID_RAG_RERANK_ENABLED=true
HYBRID_RAG_RERANKER_MODEL=BAAI/bge-reranker-base
HYBRID_RAG_BM25_WEIGHT=0.30
HYBRID_RAG_VECTOR_WEIGHT=0.30
HYBRID_RAG_GRAPH_WEIGHT=0.25
HYBRID_RAG_SOURCE_WEIGHT=0.15
HYBRID_RAG_RERANKER_WEIGHT=0.35
```

不设置 `QDRANT_URL` 时，向量保存在 `COURSEGRAPH_DATA_DIR/qdrant`。独立部署 Qdrant 时设置：

```text
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
```

## 索引生命周期

- 上传或删除课件后，课程向量索引进入 `pending` 状态。
- 下一次语义检索会计算文本块指纹，只在内容或模型变化时重建索引。
- Qdrant Payload 保存课程、文档、文本块、页码和内容哈希，查询时强制按课程过滤。
- `/api/integrations` 返回模型、向量库模式以及索引同步状态。

## 评测

先运行以下命令验证中文 Embedding、Qdrant 入库和语义召回：

```powershell
cd D:\AIGC
.\backend\.venv\Scripts\python.exe scripts\verify-hybrid-retrieval.py
```

运行 `scripts/run-qa-evaluation.py` 后生成逐题 CSV 和汇总 JSON。汇总指标包括：

- `Recall@5`：正确来源是否进入前五条证据。
- `MRR`：正确来源首次出现位置的倒数均值。
- 拒答准确率。
- 回答测试通过率。
- 平均响应时间与 P95 响应时间。

论文实验应分别关闭向量检索、图谱扩展和重排序器，比较 BM25、向量、BM25+向量、BM25+向量+图谱和完整模型。
