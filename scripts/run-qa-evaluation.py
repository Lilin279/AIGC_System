from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    args = parser.parse_args()

    login = request_json(
        f"{args.base_url}/api/auth/login", "POST",
        {"username": args.username, "password": args.password},
    )
    token = login["token"]
    rows = list(csv.DictReader(args.dataset.open("r", encoding="utf-8-sig", newline="")))
    results: list[dict] = []
    for row in rows:
        started = time.perf_counter()
        try:
            result = request_json(
                f"{args.base_url}/api/courses/{row['course_id']}/qa", "POST",
                {"question": row["question"]}, token,
            )
            serialized = json.dumps(result, ensure_ascii=False)
            expected_terms = [term for term in row["expected_terms"].split("|") if term]
            refused = "没有足够证据" in result.get("answer", "") or "不知道" in result.get("answer", "")
            expected_refusal = row["should_refuse"].lower() == "true"
            passed = refused if expected_refusal else all(term in serialized for term in expected_terms)
            error = ""
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            result, passed, error = {}, False, str(exc)
        results.append({
            **row,
            "passed": passed,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "mode": result.get("mode", ""),
            "confidence": result.get("confidence", ""),
            "answer": result.get("answer", ""),
            "evidence": json.dumps(result.get("evidence", []), ensure_ascii=False),
            "error": error,
        })
        print(f"{row['case_id']}: {'PASS' if passed else 'FAIL'} ({results[-1]['latency_ms']} ms)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    passed_count = sum(bool(item["passed"]) for item in results)
    print(f"完成：{passed_count}/{len(results)} 通过，结果写入 {args.output}")


if __name__ == "__main__":
    main()
