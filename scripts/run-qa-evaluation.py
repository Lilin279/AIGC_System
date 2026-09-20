from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def score_answer(answer: str, expected_terms: list[str], expected_refusal: bool) -> dict:
    normalized_answer = normalized(answer)
    term_coverage = (
        sum(normalized(term) in normalized_answer for term in expected_terms) / len(expected_terms)
        if expected_terms else 1.0
    )
    scope_refusal = any(marker in answer for marker in (
        "没有足够证据", "无法回答", "无法据此", "没有提供", "未检索到直接证据", "超出本课程",
    ))
    supplement = answer.partition("补充知识：")[2].strip()
    strict_refusal = scope_refusal and len(supplement) < 50
    passed = strict_refusal if expected_refusal else math.isclose(term_coverage, 1.0)
    return {
        "passed": passed,
        "answer_term_coverage": round(term_coverage, 4),
        "scope_refusal": scope_refusal,
        "strict_refusal": strict_refusal,
    }


def request_json(url: str, method: str = "GET", payload: dict | None = None, token: str = "") -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="运行课程 GraphRAG 问答验收集")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="teacher")
    parser.add_argument("--password", default="Teacher123!")
    parser.add_argument("--dataset", type=Path, default=ROOT / "sample_data/evaluation/qa-test-set.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/results/qa-results.csv")
    parser.add_argument("--summary", type=Path, default=ROOT / "docs/results/qa-summary.json")
    parser.add_argument("--reuse-results", action="store_true", help="复用已有 CSV 答案并重新计算指标")
    args = parser.parse_args()

    rows = list(csv.DictReader(args.dataset.open("r", encoding="utf-8-sig", newline="")))
    existing = {
        item["case_id"]: item
        for item in csv.DictReader(args.output.open("r", encoding="utf-8-sig", newline=""))
    } if args.reuse_results and args.output.exists() else {}
    token = ""
    if not existing:
        login = request_json(
            f"{args.base_url}/api/auth/login", "POST",
            {"username": args.username, "password": args.password},
        )
        token = login["token"]
    results: list[dict] = []
    for row in rows:
        started = time.perf_counter()
        try:
            if row["case_id"] in existing:
                previous = existing[row["case_id"]]
                result = {
                    "mode": previous.get("mode", ""),
                    "confidence": previous.get("confidence", ""),
                    "answer": previous.get("answer", ""),
                    "evidence": json.loads(previous.get("evidence", "[]") or "[]"),
                }
                measured_latency = int(previous.get("latency_ms", 0) or 0)
            else:
                result = request_json(
                    f"{args.base_url}/api/courses/{row['course_id']}/qa", "POST",
                    {"question": row["question"]}, token,
                )
                measured_latency = round((time.perf_counter() - started) * 1000)
            expected_terms = [term for term in row["expected_terms"].split("|") if term]
            evidence = result.get("evidence", [])
            expected_source = row.get("expected_source", "").strip()
            source_ranks = [
                index for index, item in enumerate(evidence, start=1)
                if expected_source and expected_source in str(item.get("source", ""))
            ]
            expected_refusal = row["should_refuse"].lower() == "true"
            answer_scores = score_answer(result.get("answer", ""), expected_terms, expected_refusal)
            passed = answer_scores["passed"]
            retrieval_hit_at_5 = bool(source_ranks and source_ranks[0] <= 5) if not expected_refusal else None
            reciprocal_rank = (1 / source_ranks[0]) if source_ranks and not expected_refusal else 0.0
            error = ""
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            result, passed, error = {}, False, str(exc)
            evidence, expected_refusal, retrieval_hit_at_5, reciprocal_rank = [], False, False, 0.0
            measured_latency = round((time.perf_counter() - started) * 1000)
            answer_scores = {"answer_term_coverage": 0.0, "scope_refusal": False, "strict_refusal": False}
        results.append({
            **row,
            "passed": passed,
            "latency_ms": measured_latency,
            "mode": result.get("mode", ""),
            "confidence": result.get("confidence", ""),
            "answer": result.get("answer", ""),
            "answer_term_coverage": answer_scores["answer_term_coverage"],
            "scope_refusal": answer_scores["scope_refusal"],
            "strict_refusal": answer_scores["strict_refusal"],
            "retrieval_hit_at_5": retrieval_hit_at_5,
            "reciprocal_rank": round(reciprocal_rank, 6),
            "citation_count": len(evidence),
            "top_final_score": evidence[0].get("final_score", "") if evidence else "",
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "error": error,
        })
        print(f"{row['case_id']}: {'PASS' if passed else 'FAIL'} ({results[-1]['latency_ms']} ms)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    passed_count = sum(bool(item["passed"]) for item in results)
    retrieval_rows = [item for item in results if str(item["should_refuse"]).lower() != "true"]
    refusal_rows = [item for item in results if str(item["should_refuse"]).lower() == "true"]
    latencies = sorted(int(item["latency_ms"]) for item in results)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    summary = {
        "cases": len(results),
        "answer_pass_rate": round(passed_count / max(1, len(results)), 4),
        "in_domain_answer_accuracy": round(
            sum(bool(item["passed"]) for item in retrieval_rows) / max(1, len(retrieval_rows)), 4,
        ),
        "recall_at_5": round(
            sum(item["retrieval_hit_at_5"] is True for item in retrieval_rows) / max(1, len(retrieval_rows)), 4,
        ),
        "mrr": round(sum(float(item["reciprocal_rank"]) for item in retrieval_rows) / max(1, len(retrieval_rows)), 4),
        "refusal_accuracy": round(
            sum(bool(item["passed"]) for item in refusal_rows) / max(1, len(refusal_rows)), 4,
        ),
        "scope_refusal_rate": round(
            sum(str(item["scope_refusal"]).lower() == "true" for item in refusal_rows) / max(1, len(refusal_rows)), 4,
        ),
        "latency_ms": {
            "mean": round(sum(latencies) / max(1, len(latencies))),
            "p95": latencies[p95_index] if latencies else 0,
        },
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{passed_count}/{len(results)} 通过，结果写入 {args.output}")
    print(f"Recall@5={summary['recall_at_5']}，MRR={summary['mrr']}，拒答准确率={summary['refusal_accuracy']}")


if __name__ == "__main__":
    main()
