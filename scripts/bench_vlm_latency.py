#!/usr/bin/env python
"""Bench the VLM image path so PARALLEL_VISION_IDENTITY is flipped on DATA, not vibes (item 5).

Two measurements, both run on the SAME demo image set so the numbers are comparable:

  1. vision_cache cold vs warm — calls identify_product_from_image twice per image. The first call
     pays the full VLM cost; the second should be a cache hit (<1s). This quantifies the prewarm win.

  2. PARALLEL_VISION_IDENTITY off vs on — runs the same image queries through the /suggest route via
     an in-process TestClient with the flag toggled (temp feature-flags file), and reports p50/p95.

It prints a FLIP GATE verdict: only flip PARALLEL_VISION_IDENTITY on when the parallel run's p95 is
materially better (>= ~15%) with NO increase in errors. The flag ships OFF until you see that here.

Usage (on demo hardware with Ollama + a vision model running):
    OLLAMA_HOST=... CV_IDENTITY_MODEL=qwen2.5vl python scripts/bench_vlm_latency.py
    python scripts/bench_vlm_latency.py --dir dump/test-cv --runs 5

This is a measurement tool, not a test — it never flips the flag itself.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp")
_DEFAULT_DIR = os.path.join("dump", "test-cv")
_DEMO_QUERY = "what is this and what's a good one for gaming?"


def _pctl(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1)))))
    return xs[k]


def _summary(label, samples_ms, errors):
    if not samples_ms:
        print(f"  {label:<22} no samples (errors={errors})")
        return None
    p50, p95 = _pctl(samples_ms, 50), _pctl(samples_ms, 95)
    print(f"  {label:<22} n={len(samples_ms):<3} p50={p50:7.0f}ms p95={p95:7.0f}ms "
          f"mean={statistics.mean(samples_ms):7.0f}ms errors={errors}")
    return {"p50": p50, "p95": p95, "errors": errors, "n": len(samples_ms)}


def _images(directory):
    root = directory if os.path.isabs(directory) else os.path.join(_REPO_ROOT, directory)
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, n) for n in sorted(os.listdir(root)) if n.lower().endswith(_IMAGE_EXTS)]


def bench_vision_cache(images, runs):
    """Measure identify_product_from_image cold (miss) vs warm (cache hit)."""
    from src.app.services import vision_cache
    from src.app.services.product_identity_agent import identify_product_from_image

    print("\n[1] vision_cache cold vs warm (identify_product_from_image)")
    cold, warm = [], []
    cold_err = warm_err = 0
    for path in images:
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
        except Exception:
            continue
        vision_cache.clear()  # force a cold miss
        t0 = time.perf_counter()
        r0 = identify_product_from_image(blob, user_query="", trace_id=None)
        cold.append((time.perf_counter() - t0) * 1000)
        cold_err += 0 if r0.get("ok") or r0.get("from_cache") else 1
        for _ in range(max(1, runs - 1)):
            t1 = time.perf_counter()
            r1 = identify_product_from_image(blob, user_query="", trace_id=None)
            warm.append((time.perf_counter() - t1) * 1000)
            warm_err += 0 if r1.get("from_cache") else 1  # warm SHOULD be a cache hit
    c = _summary("cold (cache miss)", cold, cold_err)
    w = _summary("warm (cache hit)", warm, warm_err)
    if c and w and w["p50"] > 0:
        print(f"  -> cache speedup p50: {c['p50'] / max(1.0, w['p50']):.1f}x")


def _run_suggest(client, images, runs):
    samples, errors = [], 0
    for path in images:
        name = os.path.basename(path)
        for _ in range(runs):
            params = {"uid": f"bench_{name}", "query": _DEMO_QUERY,
                      "image_labels": "laptop", "image_hash": f"bench-{name}"}
            t0 = time.perf_counter()
            try:
                r = client.get("/api/v1/recommend/suggest", params=params, headers={"x-api-key": "local-merchant-key"})
                samples.append((time.perf_counter() - t0) * 1000)
                if r.status_code != 200:
                    errors += 1
            except Exception:
                errors += 1
    return samples, errors


def bench_parallel_flag(images, runs):
    """Measure /suggest p50/p95 with PARALLEL_VISION_IDENTITY off vs on (temp flags file)."""
    import tempfile
    from fastapi.testclient import TestClient

    from src.app.config import get_settings, load_feature_flags

    base = load_feature_flags(get_settings().feature_flags_path)
    print("\n[2] /suggest latency: PARALLEL_VISION_IDENTITY off vs on")
    results = {}
    for mode, val in (("off", False), ("on", True)):
        flags = dict(base)
        flags["PARALLEL_VISION_IDENTITY"] = val
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(flags, fh)
            fp = fh.name
        os.environ["FEATURE_FLAGS_PATH"] = fp
        # Re-import app fresh so the flag path is picked up.
        from src.app.main import create_app
        client = TestClient(create_app())
        samples, errors = _run_suggest(client, images, runs)
        results[mode] = _summary(f"parallel={mode}", samples, errors)
        try:
            os.unlink(fp)
        except Exception:
            pass
    off, on = results.get("off"), results.get("on")
    print("\nFLIP GATE:")
    if not (off and on):
        print("  insufficient data — run on demo hardware with a live VLM.")
        return
    improved = on["p95"] <= off["p95"] * 0.85
    no_new_errors = on["errors"] <= off["errors"]
    if improved and no_new_errors:
        print(f"  ✅ FLIP: parallel p95 {on['p95']:.0f}ms <= 85% of {off['p95']:.0f}ms, errors not worse.")
        print("     Set PARALLEL_VISION_IDENTITY=true in config/feature_flags.json (commit the data).")
    else:
        print(f"  ❌ HOLD: parallel p95 {on['p95']:.0f}ms vs off {off['p95']:.0f}ms "
              f"(need <= {off['p95'] * 0.85:.0f}ms) / errors off={off['errors']} on={on['errors']}.")
        print("     Keep PARALLEL_VISION_IDENTITY=false.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=_DEFAULT_DIR)
    ap.add_argument("--runs", type=int, default=3, help="iterations per image (default 3)")
    ap.add_argument("--skip-suggest", action="store_true", help="only the vision_cache bench")
    args = ap.parse_args()

    images = _images(args.dir)
    if not images:
        print(f"No images in {args.dir}. Nothing to bench.")
        return 1
    print(f"Benchmarking {len(images)} image(s) x {args.runs} run(s) from {args.dir}\n"
          f"CV_IDENTITY_MODEL={os.getenv('CV_IDENTITY_MODEL', '(default)')} "
          f"OLLAMA_HOST={os.getenv('OLLAMA_HOST', '(default)')}")
    if not os.getenv("OLLAMA_HOST") and not os.getenv("OLLAMA_URL"):
        print("  [warn] no OLLAMA_HOST set — numbers reflect the degraded/no-VLM path, not real latency.")
    bench_vision_cache(images, args.runs)
    if not args.skip_suggest:
        bench_parallel_flag(images, args.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
