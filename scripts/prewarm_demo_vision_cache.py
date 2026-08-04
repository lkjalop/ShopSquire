#!/usr/bin/env python
"""Track 3 — pre-warm the VISION cache for a live demo.

The sibling `prewarm_demo_cache.py` warms the semantic *response* cache (text
queries). This one warms the *vision* cache (`services/vision_cache.py`), which
keys the expensive VLM calls by sha256(image_bytes). The VLM is the dominant
image-path latency (measured 50-86s cold), and it runs THREE times per upload —
once for product identity and once each for the `triage` and `visual_search`
label modes — so an un-warmed first on-stage upload pays the full cost.

Running this once before the demo populates every namespace the live path reads
(`identity`, `labels:triage`, `labels:visual_search`) for each demo image, so the
first real upload is a cache hit (<1s). It is deliberately idempotent: re-running
just confirms hits. Fail-open — a model/Ollama error on one image is reported and
skipped, never fatal.

Usage:
    python scripts/prewarm_demo_vision_cache.py                 # default: dump/test-cv
    python scripts/prewarm_demo_vision_cache.py --dir path/to/images
    python scripts/prewarm_demo_vision_cache.py --identity-only # skip label modes

Env that must match the live server (otherwise you warm the wrong keys):
    CV_PROVIDER, CV_MODEL, CV_IDENTITY_MODEL, OLLAMA_HOST, VISION_CACHE_ENABLED=1
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# Bootstrap repo root so `import src...` works when run as a script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp", ".gif")
_DEFAULT_DIR = os.path.join("dump", "test-cv")
_LABEL_MODES = ("triage", "visual_search")


def _discover_images(directory: str) -> list[str]:
    root = directory if os.path.isabs(directory) else os.path.join(_REPO_ROOT, directory)
    if not os.path.isdir(root):
        print(f"[ERR] image dir not found: {root}")
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if name.lower().endswith(_IMAGE_EXTS):
            out.append(os.path.join(root, name))
    return out


def _warm_one(path: str, *, identity_only: bool) -> bool:
    """Warm every vision-cache namespace for one image. Returns True on any success."""
    from src.app.services import vision_cache as vcache
    from src.app.services.cv_provider import ManagedCVProvider
    from src.app.services.product_identity_agent import identify_product_from_image

    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] read {os.path.basename(path)}: {exc}")
        return False
    if not blob:
        print(f"[skip] empty file {os.path.basename(path)}")
        return False

    name = os.path.basename(path)
    any_ok = False

    # 1) identity namespace (the leg the parallel VLM future joins on)
    t0 = time.time()
    res = identify_product_from_image(blob, user_query="", trace_id=None)
    dt = time.time() - t0
    cached = bool(res.get("from_cache"))
    ok = bool(res.get("ok")) or cached
    any_ok = any_ok or ok
    tag = "HIT" if cached else ("ok" if ok else "miss")
    print(f"  identity            {dt:5.1f}s [{tag}] {name} -> "
          f"{res.get('brand')}/{res.get('model')} conf={res.get('confidence')}")

    if not identity_only:
        provider = ManagedCVProvider()
        for mode in _LABEL_MODES:
            t0 = time.time()
            try:
                labels, text, _ = asyncio.run(provider.get_labels_and_text(blob, mode=mode))
                dt = time.time() - t0
                # A second call confirms the warm key is a hit (cheap, in-proc).
                any_ok = any_ok or bool(labels or text)
                print(f"  labels:{mode:<13}{dt:5.1f}s [ok] {name} -> {len(labels)} labels")
            except Exception as exc:  # noqa: BLE001
                print(f"  labels:{mode:<13}  [ERR] {name}: {exc}")
    return any_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=_DEFAULT_DIR, help=f"image directory (default {_DEFAULT_DIR})")
    ap.add_argument("--identity-only", action="store_true",
                    help="warm only the identity namespace (skip triage/visual_search labels)")
    args = ap.parse_args()

    if str(os.getenv("VISION_CACHE_ENABLED", "1")).strip().lower() not in ("1", "true", "yes", "on"):
        print("[WARN] VISION_CACHE_ENABLED is off — warming will not persist. Set VISION_CACHE_ENABLED=1.")

    images = _discover_images(args.dir)
    if not images:
        print("No images found. Nothing to warm.")
        return 1

    print(f"Pre-warming vision cache for {len(images)} image(s) from {args.dir}\n"
          f"CV_PROVIDER={os.getenv('CV_PROVIDER', 'none')} CV_MODEL={os.getenv('CV_MODEL', 'llava')} "
          f"CV_IDENTITY_MODEL={os.getenv('CV_IDENTITY_MODEL', '(default)')}\n")

    ok = 0
    for path in images:
        print(os.path.basename(path))
        if _warm_one(path, identity_only=args.identity_only):
            ok += 1
    print(f"\nWarmed {ok}/{len(images)} image(s). Re-run to confirm sub-second [HIT]s.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
