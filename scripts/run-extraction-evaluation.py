from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def normalize(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).casefold()


def metrics(predicted: set, expected: set) -> dict[str, float | int]:
    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "predicted": len(predicted),
        "expected": len(expected),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="知识抽取实体/关系银标评测")
    parser.add_argument("--mode", choices=("mock", "deepseek"), default="mock")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/results/extraction-summary.json")
    args = parser.parse_args()

    if args.mode == "mock":
        os.environ["DEEPSEEK_API_KEY"] = ""
    from app.models import KnowledgeGraph
    from app.services import deepseek

    if args.mode == "deepseek" and not deepseek.configured():
        raise SystemExit("未配置 DEEPSEEK_API_KEY，无法运行在线抽取评测")

    courses = {
        "python_intro": ("Python 程序设计基础", ROOT / "sample_data/documents/python_intro.md"),
        "database_systems": ("数据库系统原理", ROOT / "sample_data/documents/database_systems.txt"),
    }
    all_predicted_nodes: set[tuple[str, str]] = set()
    all_expected_nodes: set[tuple[str, str]] = set()
    all_predicted_edges: set[tuple[str, str, str, str]] = set()
    all_expected_edges: set[tuple[str, str, str, str]] = set()
    details: list[dict] = []
    for course_id, (course_name, document_path) in courses.items():
        gold = KnowledgeGraph(**json.loads(
            (ROOT / "sample_data/graphs" / f"{course_id}.json").read_text(encoding="utf-8")
        ))
        content = document_path.read_text(encoding="utf-8")
        warnings: list[str] = []
        started = time.perf_counter()
        predicted = deepseek.extract_graph(
            course_name,
            [{"id": f"sample_{course_id}", "filename": document_path.name, "content": content}],
            warnings=warnings,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        gold_names = {node.id: normalize(node.name) for node in gold.nodes}
        predicted_names = {node.id: normalize(node.name) for node in predicted.nodes}
        expected_nodes = {(course_id, value) for value in gold_names.values()}
        predicted_nodes = {(course_id, value) for value in predicted_names.values()}
        expected_edges = {
            (course_id, gold_names[edge.source], gold_names[edge.target], edge.relation)
            for edge in gold.edges if edge.source in gold_names and edge.target in gold_names
        }
        predicted_edges = {
            (course_id, predicted_names[edge.source], predicted_names[edge.target], edge.relation)
            for edge in predicted.edges if edge.source in predicted_names and edge.target in predicted_names
        }
        all_expected_nodes |= expected_nodes
        all_predicted_nodes |= predicted_nodes
        all_expected_edges |= expected_edges
        all_predicted_edges |= predicted_edges
        source_items = [*predicted.nodes, *predicted.edges]
        source_covered = sum(bool(item.source_refs) for item in source_items)
        details.append({
            "course_id": course_id,
            "latency_ms": elapsed_ms,
            "entity": metrics(predicted_nodes, expected_nodes),
            "relation": metrics(predicted_edges, expected_edges),
            "source_traceability": round(source_covered / max(1, len(source_items)), 4),
            "warnings": warnings,
            "predicted_node_names": [node.name for node in predicted.nodes],
        })

    report = {
        "mode": args.mode,
        "reference_type": "项目示例图谱银标；非独立双人标注，因此只用于工程回归，不能替代正式论文实验",
        "courses": len(courses),
        "entity": metrics(all_predicted_nodes, all_expected_nodes),
        "relation": metrics(all_predicted_edges, all_expected_edges),
        "mean_latency_ms": round(sum(item["latency_ms"] for item in details) / len(details)),
        "details": details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("mode", "entity", "relation", "mean_latency_ms")}, ensure_ascii=False, indent=2))
    print(f"结果写入 {args.output}")


if __name__ == "__main__":
    main()
