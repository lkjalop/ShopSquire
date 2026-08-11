"""Run real local-image concurrency and disconnect certification against Ollama."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.app.services.cv_vision_ollama import vision_analyze_with_ollama  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--model", default="qwen3-vl:8b")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", default="tmp/live_image_provider_certification.json")
    args = parser.parse_args()
    image_path = Path(args.image)
    image_bytes = image_path.read_bytes()
    count = max(2, min(args.concurrency, 4))
    started = time.perf_counter()

    def invoke(index: int):
        result = vision_analyze_with_ollama(
            image_bytes,
            prompt_context=f"concurrent certification request {index}",
            model=args.model,
            timeout_s=args.timeout,
        )
        return {"request": index, **result}

    results = []
    with ThreadPoolExecutor(max_workers=count, thread_name_prefix="live-image-cert") as pool:
        futures = [pool.submit(invoke, index) for index in range(count)]
        for future in as_completed(futures):
            results.append(future.result())

    previous_url = os.getenv("OLLAMA_URL")
    os.environ["OLLAMA_URL"] = "http://127.0.0.1:65534"
    disconnect_started = time.perf_counter()
    try:
        disconnect = vision_analyze_with_ollama(
            image_bytes, model=args.model, timeout_s=0.5,
        )
    finally:
        if previous_url is None:
            os.environ.pop("OLLAMA_URL", None)
        else:
            os.environ["OLLAMA_URL"] = previous_url
    disconnect_elapsed_ms = int((time.perf_counter() - disconnect_started) * 1000)
    artifact = {
        "schema_version": "live-image-provider-cert-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "image": {"path": str(image_path), "bytes": len(image_bytes)},
        "model": args.model,
        "concurrency": count,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "concurrent_results": sorted(results, key=lambda item: item["request"]),
        "concurrent_success_count": sum(1 for item in results if item.get("ok") is True),
        "disconnect_result": disconnect,
        "disconnect_elapsed_ms": disconnect_elapsed_ms,
        "passed": bool(
            len(results) == count
            and all(item.get("ok") is True for item in results)
            and disconnect.get("ok") is False
            and disconnect_elapsed_ms < 2000
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": artifact["passed"],
        "concurrent_success_count": artifact["concurrent_success_count"],
        "concurrency": count,
        "elapsed_ms": artifact["elapsed_ms"],
        "disconnect_elapsed_ms": disconnect_elapsed_ms,
        "output": str(output),
    }, indent=2))
    return 0 if artifact["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
