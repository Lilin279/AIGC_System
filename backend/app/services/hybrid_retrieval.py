from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database import DATA_DIR, connect


@dataclass(frozen=True)
class HybridRetrievalConfig:
    enabled: bool
    embedding_model: str
    reranker_model: str
    rerank_enabled: bool
    qdrant_url: str
    qdrant_api_key: str
    vector_path: Path
    bm25_weight: float
    vector_weight: float
    graph_weight: float
    source_weight: float
    reranker_weight: float
    candidate_limit: int


@dataclass(frozen=True)
class RankedEvidence:
    evidence: list[dict[str, Any]]
    mode: str
    message: str = ""


_runtime_lock = threading.RLock()
_embedding_models: dict[str, Any] = {}
_reranker_models: dict[str, Any] = {}
_vector_clients: dict[str, Any] = {}


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def config() -> HybridRetrievalConfig:
    return HybridRetrievalConfig(
        enabled=_flag("HYBRID_RAG_ENABLED"),
        embedding_model=os.environ.get("HYBRID_RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip(),
        reranker_model=os.environ.get("HYBRID_RAG_RERANKER_MODEL", "BAAI/bge-reranker-base").strip(),
        rerank_enabled=_flag("HYBRID_RAG_RERANK_ENABLED", True),
        qdrant_url=os.environ.get("QDRANT_URL", "").strip(),
        qdrant_api_key=os.environ.get("QDRANT_API_KEY", "").strip(),
        vector_path=Path(os.environ.get("QDRANT_LOCAL_PATH", DATA_DIR / "qdrant")),
        bm25_weight=_number("HYBRID_RAG_BM25_WEIGHT", 0.30),
        vector_weight=_number("HYBRID_RAG_VECTOR_WEIGHT", 0.30),
        graph_weight=_number("HYBRID_RAG_GRAPH_WEIGHT", 0.25),
        source_weight=_number("HYBRID_RAG_SOURCE_WEIGHT", 0.15),
        reranker_weight=max(0.0, min(1.0, _number("HYBRID_RAG_RERANKER_WEIGHT", 0.35))),
        candidate_limit=max(8, min(40, int(_number("HYBRID_RAG_CANDIDATE_LIMIT", 16)))),
    )


def configured() -> bool:
    return config().enabled


def close_runtime() -> None:
    with _runtime_lock:
        for client in _vector_clients.values():
            try:
                client.close()
            except Exception:
                pass
        _vector_clients.clear()
        _embedding_models.clear()
        _reranker_models.clear()


def status() -> dict[str, Any]:
    settings = config()
    dependencies_available = bool(
        importlib.util.find_spec("fastembed") and importlib.util.find_spec("qdrant_client")
    )
    with connect() as connection:
        counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM vector_index_state GROUP BY status"
            ).fetchall()
        }
    return {
        "enabled": settings.enabled,
        "available": settings.enabled and dependencies_available,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model if settings.rerank_enabled else "disabled",
        "vector_store": "qdrant-server" if settings.qdrant_url else "qdrant-local",
        "indexes": {
            "synced": counts.get("synced", 0),
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
        },
        "message": (
            "混合检索已启用"
            if settings.enabled and dependencies_available
            else "缺少 fastembed 或 qdrant-client 依赖"
            if settings.enabled
            else "混合检索未启用"
        ),
    }


def mark_course_dirty(course_id: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO vector_index_state(course_id, model, fingerprint, status, message)
            VALUES (?, '', '', 'pending', '课程资料已变化，等待重建向量索引')
            ON CONFLICT(course_id) DO UPDATE SET
              status = 'pending', message = excluded.message, updated_at = CURRENT_TIMESTAMP
            """,
            (course_id,),
        )


def semantic_candidates(course_id: str, query: str, limit: int | None = None) -> tuple[list[dict[str, Any]], str]:
    settings = config()
    if not settings.enabled or not query.strip():
        return [], "disabled"
    try:
        client, collection = _ensure_course_index(course_id, settings)
        if client is None:
            return [], "hybrid-degraded"
        from qdrant_client import models

        model = _embedding_model(settings)
        vectors = list(model.query_embed([query])) if hasattr(model, "query_embed") else list(model.embed([query]))
        if not vectors:
            return [], "hybrid-degraded"
        response = client.query_points(
            collection_name=collection,
            query=vectors[0].tolist(),
            query_filter=models.Filter(
                must=[models.FieldCondition(key="course_id", match=models.MatchValue(value=course_id))]
            ),
            with_payload=True,
            limit=limit or settings.candidate_limit,
        )
        evidence: list[dict[str, Any]] = []
        for point in response.points:
            payload = point.payload or {}
            page_no = payload.get("page_no")
            source = str(payload.get("filename") or "课程资料")
            if page_no:
                source += f"（第 {page_no} 页）"
            evidence.append({
                "id": str(payload.get("chunk_id", "")),
                "source": source,
                "excerpt": str(payload.get("content", ""))[:500],
                "type": "document",
                "document_id": str(payload.get("document_id", "")),
                "page_no": page_no,
                "vector_score": round(float(point.score), 6),
                "source_score": _document_source_score(page_no, str(payload.get("content", ""))),
                "vector_backend": "qdrant",
            })
        return evidence, "hybrid"
    except Exception as exc:
        _record_failure(course_id, settings.embedding_model, str(exc))
        return [], "hybrid-degraded"


def rank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    limit: int = 8,
    retrieval_mode: str = "hybrid",
) -> RankedEvidence:
    settings = config()
    fused = fuse_candidates(candidates, settings)
    if not fused:
        return RankedEvidence([], retrieval_mode)
    mode = retrieval_mode
    message = ""
    if settings.enabled and settings.rerank_enabled:
        try:
            model = _reranker_model(settings)
            texts = [f"{item.get('source', '')}\n{item.get('excerpt', '')}" for item in fused]
            raw_scores = [float(score) for score in model.rerank(query, texts)]
            probabilities = [_sigmoid(score) for score in raw_scores]
            for item, raw_score, probability in zip(fused, raw_scores, probabilities):
                item["reranker_score"] = round(probability, 6)
                item["reranker_raw_score"] = round(raw_score, 6)
                item["final_score"] = round(
                    (1 - settings.reranker_weight) * item["hybrid_score"]
                    + settings.reranker_weight * probability,
                    6,
                )
            fused.sort(key=lambda item: item["final_score"], reverse=True)
        except Exception as exc:
            mode = "hybrid-degraded"
            message = f"Cross-Encoder 不可用，已按融合分数排序：{exc}"
    for rank, item in enumerate(fused[:limit], start=1):
        item["rank"] = rank
        item["retrieval_mode"] = mode
    return RankedEvidence(fused[:limit], mode, message)


def fuse_candidates(
    candidates: list[dict[str, Any]],
    settings: HybridRetrievalConfig | None = None,
) -> list[dict[str, Any]]:
    settings = settings or config()
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        key = _candidate_key(candidate, index)
        current = merged.setdefault(key, dict(candidate))
        for field in ("bm25_score", "vector_score", "node_match_score", "graph_score", "source_score"):
            value = candidate.get(field)
            if value is None:
                continue
            if field == "bm25_score":
                if current.get(field) is None or float(value) < float(current[field]):
                    current[field] = value
            else:
                current[field] = max(float(current.get(field, 0.0)), float(value))
        if candidate.get("vector_backend"):
            current["vector_backend"] = candidate["vector_backend"]

    items = list(merged.values())
    bm25_values = [-float(item["bm25_score"]) for item in items if item.get("bm25_score") is not None]
    node_values = [float(item.get("node_match_score", 0.0)) for item in items]
    normalized_bm25 = _normalizer(bm25_values)
    normalized_nodes = _normalizer([value for value in node_values if value > 0])
    weights = _normalized_weights(settings)
    for item in items:
        bm25 = normalized_bm25(-float(item["bm25_score"])) if item.get("bm25_score") is not None else 0.0
        vector = max(0.0, min(1.0, float(item.get("vector_score", 0.0))))
        graph = max(0.0, min(1.0, float(item.get("graph_score", 0.0))))
        if item.get("node_match_score"):
            graph = max(graph, normalized_nodes(float(item["node_match_score"])))
        source = max(0.0, min(1.0, float(item.get("source_score", 0.5))))
        components = {"bm25": bm25, "vector": vector, "graph": graph, "source": source}
        item["scores"] = {key: round(value, 6) for key, value in components.items()}
        item["hybrid_score"] = round(sum(weights[key] * components[key] for key in weights), 6)
        item["final_score"] = item["hybrid_score"]
    items.sort(key=lambda item: item["hybrid_score"], reverse=True)
    return items


def _ensure_course_index(course_id: str, settings: HybridRetrievalConfig) -> tuple[Any | None, str]:
    with connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """
            SELECT dc.id AS chunk_id, dc.document_id, dc.course_id, dc.page_no, dc.content, d.filename
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE dc.course_id = ? AND d.status = 'active'
            ORDER BY dc.document_id, dc.chunk_index
            """,
            (course_id,),
        ).fetchall()]
        state = connection.execute(
            "SELECT model, fingerprint, status FROM vector_index_state WHERE course_id = ?", (course_id,)
        ).fetchone()
    fingerprint = _fingerprint(rows, settings.embedding_model)
    model = _embedding_model(settings)
    client = _vector_client(settings)
    collection = _collection_name(settings.embedding_model)
    _ensure_collection(client, collection, int(model.embedding_size))
    if state and state["status"] == "synced" and state["model"] == settings.embedding_model and state["fingerprint"] == fingerprint:
        return client, collection

    from qdrant_client import models

    course_filter = models.Filter(
        must=[models.FieldCondition(key="course_id", match=models.MatchValue(value=course_id))]
    )
    client.delete(collection_name=collection, points_selector=models.FilterSelector(filter=course_filter), wait=True)
    if rows:
        contents = [row["content"] for row in rows]
        embeddings = list(model.passage_embed(contents)) if hasattr(model, "passage_embed") else list(model.embed(contents))
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, row["chunk_id"])),
                vector=embedding.tolist(),
                payload={**row, "content_hash": hashlib.sha256(row["content"].encode("utf-8")).hexdigest()},
            )
            for row, embedding in zip(rows, embeddings)
        ]
        client.upsert(collection_name=collection, points=points, wait=True)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO vector_index_state(course_id, model, fingerprint, status, chunk_count, message, synced_at)
            VALUES (?, ?, ?, 'synced', ?, '向量索引已同步', CURRENT_TIMESTAMP)
            ON CONFLICT(course_id) DO UPDATE SET
              model = excluded.model, fingerprint = excluded.fingerprint, status = 'synced',
              chunk_count = excluded.chunk_count, message = excluded.message,
              updated_at = CURRENT_TIMESTAMP, synced_at = CURRENT_TIMESTAMP
            """,
            (course_id, settings.embedding_model, fingerprint, len(rows)),
        )
    return client, collection


def _embedding_model(settings: HybridRetrievalConfig) -> Any:
    with _runtime_lock:
        if settings.embedding_model not in _embedding_models:
            from fastembed import TextEmbedding

            cache_dir = Path(os.environ.get("FASTEMBED_CACHE_DIR", DATA_DIR / "model-cache"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            _embedding_models[settings.embedding_model] = TextEmbedding(
                model_name=settings.embedding_model,
                cache_dir=str(cache_dir),
                threads=max(1, int(_number("HYBRID_RAG_THREADS", 2))),
            )
        return _embedding_models[settings.embedding_model]


def _reranker_model(settings: HybridRetrievalConfig) -> Any:
    with _runtime_lock:
        if settings.reranker_model not in _reranker_models:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            cache_dir = Path(os.environ.get("FASTEMBED_CACHE_DIR", DATA_DIR / "model-cache"))
            cache_dir.mkdir(parents=True, exist_ok=True)
            _reranker_models[settings.reranker_model] = TextCrossEncoder(
                model_name=settings.reranker_model,
                cache_dir=str(cache_dir),
                threads=max(1, int(_number("HYBRID_RAG_THREADS", 2))),
            )
        return _reranker_models[settings.reranker_model]


def _vector_client(settings: HybridRetrievalConfig) -> Any:
    key = settings.qdrant_url or str(settings.vector_path.resolve())
    with _runtime_lock:
        if key not in _vector_clients:
            from qdrant_client import QdrantClient

            if settings.qdrant_url:
                _vector_clients[key] = QdrantClient(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key or None,
                    timeout=20.0,
                )
            else:
                settings.vector_path.mkdir(parents=True, exist_ok=True)
                _vector_clients[key] = QdrantClient(path=str(settings.vector_path))
        return _vector_clients[key]


def _ensure_collection(client: Any, collection: str, dimension: int) -> None:
    if client.collection_exists(collection):
        return
    from qdrant_client import models

    client.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
    )


def _record_failure(course_id: str, model: str, message: str) -> None:
    try:
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO vector_index_state(course_id, model, fingerprint, status, message)
                VALUES (?, ?, '', 'failed', ?)
                ON CONFLICT(course_id) DO UPDATE SET
                  model = excluded.model, status = 'failed', message = excluded.message,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (course_id, model, message[:500]),
            )
    except Exception:
        pass


def _fingerprint(rows: list[dict[str, Any]], model: str) -> str:
    digest = hashlib.sha256(model.encode("utf-8"))
    for row in rows:
        digest.update(str(row["chunk_id"]).encode("utf-8"))
        digest.update(str(row["content"]).encode("utf-8"))
    return digest.hexdigest()


def _collection_name(model: str) -> str:
    return f"coursegraph_chunks_{hashlib.sha1(model.encode('utf-8')).hexdigest()[:10]}"


def _candidate_key(candidate: dict[str, Any], index: int) -> tuple[str, str]:
    candidate_type = str(candidate.get("type", "evidence"))
    identifier = str(candidate.get("id") or candidate.get("relation_id") or "")
    if not identifier:
        identifier = hashlib.sha1(
            f"{candidate.get('source', '')}|{candidate.get('excerpt', '')}|{index}".encode("utf-8")
        ).hexdigest()
    return candidate_type, identifier


def _normalizer(values: list[float]):
    if not values:
        return lambda _: 0.0
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return lambda _: 1.0
    return lambda value: max(0.0, min(1.0, (value - low) / (high - low)))


def _normalized_weights(settings: HybridRetrievalConfig) -> dict[str, float]:
    weights = {
        "bm25": max(0.0, settings.bm25_weight),
        "vector": max(0.0, settings.vector_weight),
        "graph": max(0.0, settings.graph_weight),
        "source": max(0.0, settings.source_weight),
    }
    total = sum(weights.values()) or 1.0
    return {key: value / total for key, value in weights.items()}


def _document_source_score(page_no: int | None, content: str) -> float:
    return min(1.0, 0.65 + (0.2 if page_no else 0.0) + (0.15 if content.strip() else 0.0))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-min(value, 60.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -60.0))
    return z / (1.0 + z)
