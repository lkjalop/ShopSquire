#!/usr/bin/env python
"""Build catalog indexes for retrieval.

Two indexes, selectable via --mode:

  visual      CLIP/FAISS visual-similarity index (grounding-ladder #3). Activates
              the `visual_match` evidence source. Requires sentence-transformers + faiss.

  embeddings  pgvector `product_embeddings` text index used by caption-RAG
              (candidate_retriever.from_caption). Each product is embedded from the
              CANONICAL rich text (name + brand + specs [+ VLM visual caption with
              --captions]) — fixing the legacy SKU-only embedding. Idempotent
              (ON CONFLICT upsert); Postgres-only write (no-ops cleanly on SQLite).

  both        run visual then embeddings.

Usage:
    python scripts/build_visual_index.py                      # visual (back-compat)
    python scripts/build_visual_index.py --mode embeddings    # rich-text pgvector reindex
    python scripts/build_visual_index.py --mode embeddings --captions   # + VLM captions
    python scripts/build_visual_index.py --mode both --captions
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Make `src` importable when run as `python scripts/build_visual_index.py`
# (python puts the script dir on sys.path, not the repo root).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _build_visual() -> int:
    from src.app.services import visual_search

    if not visual_search.is_available():
        print("visual_search NOT available — install: pip install sentence-transformers faiss-cpu")
        return 2

    from sqlalchemy import text as sql_text
    from src.app.models.db import db_session

    products = []
    with db_session() as db:
        try:
            rows = db.execute(sql_text(
                "SELECT sku, name, brand, price_cents, specs FROM products LIMIT 50000"
            )).fetchall()
        except Exception:
            rows = db.execute(sql_text(
                "SELECT sku, name, '' AS brand, price_cents, specs FROM products LIMIT 50000"
            )).fetchall()
        for r in rows:
            specs = {}
            if r[4]:
                try:
                    specs = json.loads(r[4]) if isinstance(r[4], str) else r[4]
                except Exception:
                    specs = {}
            products.append({"sku": r[0], "name": r[1], "brand": r[2], "price_cents": r[3], "specs": specs})

    if not products:
        print("No products found in catalog — nothing to index.")
        return 1

    n = visual_search.build_index(products, persist=True, source="manual_script")
    st = visual_search.status()
    print(f"[visual] indexed {n} products. index_size={st.get('index_size')} "
          f"quality={st.get('quality', {}).get('quality_score')}")
    return 0


def _load_image_bytes(image_url: str | None) -> bytes | None:
    """Best-effort local image load (for captioning). Remote URLs are skipped in
    batch mode to avoid SSRF + slow fetches; captioning is additive, so a miss just
    yields a text-only embedding."""
    s = str(image_url or "").strip()
    if not s or s.startswith("http"):
        return None
    rel = s.lstrip("/")
    for cand in (rel, os.path.join("static", rel), os.path.join("src", "app", "static", rel), s):
        try:
            if os.path.exists(cand) and os.path.isfile(cand):
                with open(cand, "rb") as f:
                    return f.read()
        except Exception:
            continue
    return None


def _build_embeddings(*, with_captions: bool, limit: int = 50000) -> int:
    """Reindex product_embeddings from canonical rich text (+optional VLM caption)."""
    from sqlalchemy import text as sql_text
    from src.app.models.db import db_session
    from src.app.services.embeddings import VectorStoreEmbeddings
    from src.app.repositories.embeddings import upsert_product_embedding
    from src.app.services.product_embedding_text import build_embedding_text

    captioner = None
    if with_captions:
        try:
            from src.app.services.product_captioner import caption_product
            captioner = caption_product
        except Exception as exc:
            print(f"[embeddings] captioner unavailable ({exc}); continuing text-only")

    emb_svc = VectorStoreEmbeddings()
    indexed = captioned = skipped = errors = 0
    with db_session() as db:
        try:
            rows = db.execute(sql_text(
                "SELECT id, sku, name, brand, price_cents, specs, image_url FROM products LIMIT :lim"
            ), {"lim": int(limit)}).fetchall()
        except Exception:
            rows = db.execute(sql_text(
                "SELECT id, sku, name, '' AS brand, price_cents, specs, '' AS image_url FROM products LIMIT :lim"
            ), {"lim": int(limit)}).fetchall()

        for r in rows:
            pid = str(r[0])
            product = {"id": pid, "sku": r[1], "name": r[2], "brand": r[3],
                       "price_cents": r[4], "specs": r[5], "image_url": r[6]}
            caption = None
            if captioner and product.get("image_url"):
                try:
                    img = _load_image_bytes(product["image_url"])
                    if img:
                        caption = captioner(img)
                        if caption:
                            captioned += 1
                except Exception:
                    caption = None
            emb_text = build_embedding_text(product, caption=caption)
            try:
                vec = emb_svc.embed_text_vector(emb_text)
                ok = upsert_product_embedding(db, pid, vec)
                if ok:
                    indexed += 1
                else:
                    skipped += 1  # SQLite no-op (Postgres required for pgvector write)
            except Exception:
                errors += 1
    print(f"[embeddings] indexed={indexed} captioned={captioned} skipped(non-pg)={skipped} errors={errors}")
    return 0 if (indexed or skipped) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Build catalog retrieval indexes")
    ap.add_argument("--mode", choices=["visual", "embeddings", "both"], default="visual")
    ap.add_argument("--captions", action="store_true", help="add VLM visual captions to embeddings (needs Ollama)")
    ap.add_argument("--limit", type=int, default=50000)
    args = ap.parse_args()

    rc = 0
    if args.mode in ("visual", "both"):
        rc = _build_visual() or rc
    if args.mode in ("embeddings", "both"):
        rc = _build_embeddings(with_captions=args.captions, limit=args.limit) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
