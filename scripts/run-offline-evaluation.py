from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import KnowledgeGraph  # noqa: E402
from app.services.recommender import recommend_path  # noqa: E402
from app.services.retrieval import search_tokens  # noqa: E402


def normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [1.0 if high > 0 else 0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def cosine(left, right) -> float:
    numerator = float(sum(float(a) * float(b) for a, b in zip(left, right)))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def bm25_scores(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    tokenized = [search_tokens(document) for document in documents]
    query_tokens = search_tokens(query)
    document_count = len(tokenized)
    average_length = mean([len(tokens) for tokens in tokenized]) if tokenized else 1.0
    frequencies = Counter(token for tokens in tokenized for token in set(tokens))
    scores: list[float] = []
    for tokens in tokenized:
        term_counts = Counter(tokens)
        score = 0.0
        for term in query_tokens:
            document_frequency = frequencies.get(term, 0)
            if not document_frequency:
                continue
            inverse_document_frequency = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            frequency = term_counts.get(term, 0)
            denominator = frequency + k1 * (1 - b + b * len(tokens) / max(average_length, 1))
            score += inverse_document_frequency * frequency * (k1 + 1) / max(denominator, 1e-9)
        scores.append(score)
    return scores


def graph_scores(graph: KnowledgeGraph, seed_indices: list[int]) -> list[float]:
    node_ids = [node.id for node in graph.nodes]
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in graph.edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set()).add(edge.source)
    seed_ids = [node_ids[index] for index in seed_indices]
    scores: dict[str, float] = {node_id: 0.0 for node_id in node_ids}
    frontier = set(seed_ids)
    for hop, score in ((0, 1.0), (1, 0.65), (2, 0.35)):
        for node_id in frontier:
            scores[node_id] = max(scores[node_id], score)
        next_frontier = {neighbor for node_id in frontier for neighbor in adjacency.get(node_id, set())}
        frontier = next_frontier - set(seed_ids) if hop == 0 else next_frontier
    return [scores[node_id] for node_id in node_ids]


def ranking_metrics(ranked_ids: list[str], relevant_ids: set[str], k: int = 5) -> dict[str, float]:
    top = ranked_ids[:k]
    hits = [index for index, node_id in enumerate(ranked_ids, start=1) if node_id in relevant_ids]
    recall = len(set(top) & relevant_ids) / max(1, len(relevant_ids))
    reciprocal_rank = 1 / hits[0] if hits else 0.0
    hit_at_1 = 1.0 if top and top[0] in relevant_ids else 0.0
    return {"recall_at_5": recall, "mrr": reciprocal_rank, "hit_at_1": hit_at_1}


def run_retrieval(dataset: Path, model_cache: Path) -> tuple[dict, list[dict]]:
    from fastembed import TextEmbedding

    rows = list(csv.DictReader(dataset.open("r", encoding="utf-8-sig", newline="")))
    model = TextEmbedding(
        model_name="BAAI/bge-small-zh-v1.5",
        cache_dir=str(model_cache),
        threads=max(1, min(4, os.cpu_count() or 2)),
    )
    graphs: dict[str, KnowledgeGraph] = {}
    documents: dict[str, list[str]] = {}
    passage_vectors: dict[str, list] = {}
    for course_id in sorted({row["course_id"] for row in rows}):
        graph = KnowledgeGraph(**json.loads(
            (ROOT / "sample_data" / "graphs" / f"{course_id}.json").read_text(encoding="utf-8")
        ))
        graphs[course_id] = graph
        documents[course_id] = [f"{node.name}。{node.definition}。{node.example}" for node in graph.nodes]
        passage_vectors[course_id] = list(model.passage_embed(documents[course_id]))

    query_vectors = list(model.query_embed([row["question"] for row in rows]))
    modes = ("bm25", "vector", "bm25_vector", "bm25_vector_graph")
    results: list[dict] = []
    aggregate: dict[str, list[dict[str, float]]] = {mode: [] for mode in modes}
    for row, query_vector in zip(rows, query_vectors):
        graph = graphs[row["course_id"]]
        node_ids = [node.id for node in graph.nodes]
        bm25 = normalize(bm25_scores(row["question"], documents[row["course_id"]]))
        vector = normalize([cosine(query_vector, item) for item in passage_vectors[row["course_id"]]])
        seed_indices = sorted(range(len(node_ids)), key=lambda index: bm25[index] + vector[index], reverse=True)[:3]
        graph_component = graph_scores(graph, seed_indices)
        scores_by_mode = {
            "bm25": bm25,
            "vector": vector,
            "bm25_vector": [0.5 * b + 0.5 * v for b, v in zip(bm25, vector)],
            "bm25_vector_graph": [
                0.35 * b + 0.35 * v + 0.30 * g for b, v, g in zip(bm25, vector, graph_component)
            ],
        }
        relevant = set(row["relevant_node_ids"].split("|"))
        detail = {"case_id": row["case_id"], "course_id": row["course_id"], "question": row["question"]}
        for mode, scores in scores_by_mode.items():
            ranked_ids = [node_ids[index] for index in sorted(range(len(node_ids)), key=lambda i: scores[i], reverse=True)]
            metrics = ranking_metrics(ranked_ids, relevant)
            aggregate[mode].append(metrics)
            detail[f"{mode}_top5"] = ranked_ids[:5]
            detail[f"{mode}_recall_at_5"] = round(metrics["recall_at_5"], 6)
            detail[f"{mode}_reciprocal_rank"] = round(metrics["mrr"], 6)
        results.append(detail)

    summary = {
        mode: {
            key: round(mean(item[key] for item in values), 4)
            for key in ("recall_at_5", "mrr", "hit_at_1")
        }
        for mode, values in aggregate.items()
    }
    return summary, results


def run_paths(dataset: Path) -> tuple[dict, list[dict]]:
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    graphs: dict[str, KnowledgeGraph] = {}
    results: list[dict] = []
    for case in cases:
        course_id = case["course_id"]
        if course_id not in graphs:
            graphs[course_id] = KnowledgeGraph(**json.loads(
                (ROOT / "sample_data" / "graphs" / f"{course_id}.json").read_text(encoding="utf-8")
            ))
        graph = graphs[course_id]
        result = recommend_path(graph, case["mastered_node_ids"])
        ranked = [item.node.id for item in result.recommendations]
        expected = set(case["expected_next_node_ids"])
        ranks = [index for index, node_id in enumerate(ranked, start=1) if node_id in expected]
        incoming: dict[str, set[str]] = {}
        for edge in graph.edges:
            if edge.relation == "prerequisite":
                incoming.setdefault(edge.target, set()).add(edge.source)
        mastered = set(case["mastered_node_ids"])
        constraint_valid = all(incoming.get(node_id, set()).issubset(mastered) for node_id in ranked)
        results.append({
            "case_id": case["case_id"],
            "ranked_node_ids": ranked,
            "expected_next_node_ids": sorted(expected),
            "hit_at_6": bool(expected & set(ranked[:6])),
            "reciprocal_rank": round(1 / ranks[0], 6) if ranks else 0.0,
            "constraint_valid": constraint_valid,
        })
    summary = {
        "cases": len(results),
        "hit_at_6": round(mean(float(item["hit_at_6"]) for item in results), 4),
        "mrr": round(mean(float(item["reciprocal_rank"]) for item in results), 4),
        "prerequisite_constraint_accuracy": round(mean(float(item["constraint_valid"]) for item in results), 4),
    }
    return summary, results


def main() -> None:
    parser = argparse.ArgumentParser(description="运行检索消融和推荐路径一致性评测")
    parser.add_argument(
        "--retrieval-dataset", type=Path,
        default=ROOT / "sample_data/evaluation/retrieval-ablation.csv",
    )
    parser.add_argument(
        "--path-dataset", type=Path,
        default=ROOT / "sample_data/evaluation/path-test-set.json",
    )
    parser.add_argument("--model-cache", type=Path, default=BACKEND / "data/model-cache")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/results/offline-evaluation.json")
    args = parser.parse_args()

    retrieval_summary, retrieval_cases = run_retrieval(args.retrieval_dataset, args.model_cache)
    path_summary, path_cases = run_paths(args.path_dataset)
    report = {
        "scope": {
            "retrieval_cases": len(retrieval_cases),
            "path_cases": len(path_cases),
            "dataset_type": "项目内人工构造小样本，不代表真实教学效果",
            "reranker": "未纳入本轮实模型消融",
        },
        "retrieval_ablation": retrieval_summary,
        "learning_path": path_summary,
        "retrieval_cases": retrieval_cases,
        "path_cases": path_cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"retrieval_ablation": retrieval_summary, "learning_path": path_summary}, ensure_ascii=False, indent=2))
    print(f"结果写入 {args.output}")


if __name__ == "__main__":
    main()
