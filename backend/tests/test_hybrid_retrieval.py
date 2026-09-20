from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import hybrid_retrieval


def _settings(**overrides) -> hybrid_retrieval.HybridRetrievalConfig:
    values = {
        "enabled": True,
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "reranker_model": "BAAI/bge-reranker-base",
        "rerank_enabled": True,
        "qdrant_url": "",
        "qdrant_api_key": "",
        "vector_path": Path(tempfile.gettempdir()) / "coursegraph-test-vectors",
        "bm25_weight": 0.30,
        "vector_weight": 0.30,
        "graph_weight": 0.25,
        "source_weight": 0.15,
        "reranker_weight": 0.35,
        "candidate_limit": 16,
    }
    values.update(overrides)
    return hybrid_retrieval.HybridRetrievalConfig(**values)


class _FakeReranker:
    def rerank(self, query: str, documents: list[str]):
        self.query = query
        self.documents = documents
        return [-5.0, 5.0]


class HybridRetrievalTestCase(unittest.TestCase):
    def test_fusion_merges_bm25_and_vector_hits_for_same_chunk(self) -> None:
        candidates = [
            {
                "id": "chunk-1", "type": "document", "source": "chapter.md", "excerpt": "变量保存数据",
                "bm25_score": -3.2, "source_score": 0.8,
            },
            {
                "id": "chunk-1", "type": "document", "source": "chapter.md", "excerpt": "变量保存数据",
                "vector_score": 0.92, "vector_backend": "qdrant", "source_score": 0.8,
            },
            {
                "id": "node-1", "type": "graph", "source": "知识点：变量", "excerpt": "变量用于保存数据",
                "node_match_score": 6, "graph_score": 1.0, "source_score": 0.7,
            },
        ]

        result = hybrid_retrieval.fuse_candidates(candidates, _settings())

        self.assertEqual(len(result), 2)
        chunk = next(item for item in result if item["id"] == "chunk-1")
        self.assertEqual(chunk["vector_backend"], "qdrant")
        self.assertEqual(chunk["scores"]["bm25"], 1.0)
        self.assertAlmostEqual(chunk["scores"]["vector"], 0.92)
        self.assertGreater(chunk["hybrid_score"], 0.6)

    def test_cross_encoder_reranking_changes_final_order(self) -> None:
        candidates = [
            {
                "id": "first", "type": "document", "source": "a.md", "excerpt": "关键词命中",
                "bm25_score": -5.0, "vector_score": 0.9, "source_score": 1.0,
            },
            {
                "id": "second", "type": "document", "source": "b.md", "excerpt": "语义答案",
                "bm25_score": -1.0, "vector_score": 0.5, "source_score": 1.0,
            },
        ]
        settings = _settings(reranker_weight=0.9)
        reranker = _FakeReranker()

        with (
            patch.object(hybrid_retrieval, "config", return_value=settings),
            patch.object(hybrid_retrieval, "_reranker_model", return_value=reranker),
        ):
            result = hybrid_retrieval.rank_candidates("变量是什么", candidates)

        self.assertEqual(result.mode, "hybrid")
        self.assertEqual(result.evidence[0]["id"], "second")
        self.assertGreater(result.evidence[0]["reranker_score"], result.evidence[1]["reranker_score"])

    def test_vector_failure_returns_degraded_mode(self) -> None:
        settings = _settings()
        with (
            patch.object(hybrid_retrieval, "config", return_value=settings),
            patch.object(hybrid_retrieval, "_ensure_course_index", side_effect=RuntimeError("model unavailable")),
            patch.object(hybrid_retrieval, "_record_failure") as record,
        ):
            evidence, mode = hybrid_retrieval.semantic_candidates("course", "问题")

        self.assertEqual(evidence, [])
        self.assertEqual(mode, "hybrid-degraded")
        record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
