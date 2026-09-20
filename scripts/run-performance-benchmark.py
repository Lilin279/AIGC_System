from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]


def request(url: str, token: str = "", payload: dict | None = None) -> tuple[bool, float]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET"),
            timeout=20,
        ) as response:
            response.read()
            return 200 <= response.status < 300, (time.perf_counter() - started) * 1000
    except (urllib.error.URLError, TimeoutError):
        return False, (time.perf_counter() - started) * 1000


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * ratio) - 1))
    return ordered[index]


def benchmark(url: str, token: str, total: int, concurrency: int) -> dict:
    for _ in range(min(3, total)):
        request(url, token)
    started = time.perf_counter()
    outcomes: list[tuple[bool, float]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(request, url, token) for _ in range(total)]
        for future in as_completed(futures):
            outcomes.append(future.result())
    duration = time.perf_counter() - started
    latencies = [latency for success, latency in outcomes if success]
    success_count = sum(success for success, _ in outcomes)
    return {
        "requests": total,
        "concurrency": concurrency,
        "success_rate": round(success_count / max(total, 1), 4),
        "throughput_rps": round(success_count / max(duration, 1e-9), 2),
        "latency_ms": {
            "mean": round(mean(latencies), 2) if latencies else 0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
        },
    }


def login(base_url: str, username: str, password: str) -> str:
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    request_object = urllib.request.Request(
        f"{base_url}/api/auth/login", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request_object, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))["token"]


def main() -> None:
    parser = argparse.ArgumentParser(description="只读接口并发性能基准")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="teacher")
    parser.add_argument("--password", default="Teacher123!")
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--concurrency", default="1,5,10")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/results/performance-summary.json")
    args = parser.parse_args()

    token = login(args.base_url, args.username, args.password)
    levels = [max(1, int(value)) for value in args.concurrency.split(",") if value.strip()]
    targets = {
        "health": (f"{args.base_url}/api/health", ""),
        "course_graph": (f"{args.base_url}/api/courses/python_intro/graph", token),
    }
    results = {
        name: [benchmark(url, target_token, args.requests, level) for level in levels]
        for name, (url, target_token) in targets.items()
    }
    report = {
        "environment": "本机开发环境；结果不等同于生产容量上限",
        "method": "只读接口预热后压测，每个接口每档并发独立执行",
        "targets": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"结果写入 {args.output}")


if __name__ == "__main__":
    main()
