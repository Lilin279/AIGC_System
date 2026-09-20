from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    parser = argparse.ArgumentParser(description="验证中文 Embedding 与 Qdrant 语义召回链路")
    parser.add_argument("--query", default="变量在程序中有什么作用")
    parser.add_argument("--model-cache", type=Path, default=BACKEND / "data" / "model-cache")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="coursegraph-hybrid-") as temp_dir:
        os.environ["COURSEGRAPH_DATA_DIR"] = temp_dir
        os.environ["QDRANT_LOCAL_PATH"] = str(Path(temp_dir) / "qdrant")
        os.environ["FASTEMBED_CACHE_DIR"] = str(args.model_cache)
        os.environ["HYBRID_RAG_ENABLED"] = "true"
        os.environ["HYBRID_RAG_RERANK_ENABLED"] = "false"
        sys.path.insert(0, str(BACKEND))

        from app import storage
        from app.services.hybrid_retrieval import close_runtime, semantic_candidates, status

        storage.init_store()
        try:
            evidence, mode = semantic_candidates("python_intro", args.query, 5)
            if mode != "hybrid" or not evidence:
                raise SystemExit(f"验证失败：mode={mode}, evidence={len(evidence)}")
            top = evidence[0]
            print(f"mode={mode}")
            print(f"hits={len(evidence)}")
            print(f"top_source={top['source']}")
            print(f"top_vector_score={top['vector_score']}")
            print(f"status_available={status()['available']}")
        finally:
            close_runtime()


if __name__ == "__main__":
    main()
