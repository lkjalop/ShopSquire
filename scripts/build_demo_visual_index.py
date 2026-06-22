#!/usr/bin/env python
"""Build the demo visual-similarity FAISS index so IMAGE_SIMILARITY can go live.

The visual-similarity leg is built + wired but inert until a FAISS index exists (visual_search.search
returns [] with no index). This loads the catalog and calls visual_search.build_index, then prints
the readiness so you know whether the feature is actually live.

Activation (on a host with CLIP + faiss installed):
    python scripts/build_demo_visual_index.py
    # then set IMAGE_SIMILARITY_ENABLED=1

It is fail-soft: if CLIP/faiss aren't installed it says so and exits non-zero rather than crashing —
the feature simply stays inert (no fabricated capability).
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_catalog() -> list[dict]:
    """Load active catalog products (sku, name, specs, image_url) for indexing."""
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session
        with db_session() as db:
            rows = db.execute(text(
                "SELECT sku, name, specs, image_url FROM products WHERE active = 1"
            )).mappings().all()
        out = []
        for r in rows:
            out.append({"sku": r["sku"], "name": r["name"],
                        "specs": r["specs"], "image_url": r.get("image_url")})
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not load catalog from DB: {exc}")
        # Fall back to the UI products.json if present.
        try:
            import json
            p = os.path.join(_REPO_ROOT, "static", "products.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh)
                return data if isinstance(data, list) else (data.get("products") or [])
        except Exception:
            pass
        return []


def main() -> int:
    # The import itself pulls in CLIP / sentence_transformers / faiss. If those deps
    # aren't installed it raises ModuleNotFoundError BEFORE the is_available() check —
    # so catch it here and stay fail-soft (the docstring promise) instead of a traceback.
    try:
        from src.app.services import visual_search
    except Exception as exc:  # ModuleNotFoundError: sentence_transformers / clip / faiss
        print(f"[FAIL] visual-search deps not installed ({exc}). Install the CLIP/FAISS stack "
              "(sentence_transformers, faiss-cpu) on the host, then re-run. Visual similarity "
              "stays inert and IMAGE_SIMILARITY_ENABLED must remain 0 until then.")
        return 2

    if not visual_search.is_available():
        print("[FAIL] CLIP/FAISS not available in this environment — install the visual-search deps "
              "(clip + faiss) on the host, then re-run. Visual similarity stays inert until then.")
        return 2

    products = _load_catalog()
    if not products:
        print("[FAIL] no catalog products found to index.")
        return 1

    n = visual_search.build_index(products, source="demo_build_script")
    st = visual_search.status()
    print(f"Indexed {n} product(s). index_ready={st.get('index_ready')} size={st.get('index_size')} "
          f"coverage={st.get('quality', {}).get('coverage_ratio')}")

    from src.app.services.commerce_feature_readiness import visual_search_readiness
    rd = visual_search_readiness()
    print(f"Readiness: live={rd['live']} — {rd['reason']}")
    if not rd["live"]:
        print("Note: set IMAGE_SIMILARITY_ENABLED=1 to serve visual-similarity results.")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
