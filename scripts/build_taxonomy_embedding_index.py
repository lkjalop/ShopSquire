"""Build the taxonomy embedding index (one-time per pinned release / embed model).

Embeds all 14,606 node paths with nomic-embed-text via local Ollama into
data/taxonomy/shopify-<release>/embeddings.npz (a build artifact, gitignored — ~45MB).
The classifier degrades to lexical candidates whenever this index is absent.

Run from repo root: python scripts/build_taxonomy_embedding_index.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.services.taxonomy_embedding_index import EMBED_MODEL, build_index, semantic_top_k

t0 = time.monotonic()
n = build_index()
if n is None:
    sys.exit("index build FAILED — is Ollama up and the embed model pulled? "
             f"(model={EMBED_MODEL})")
print(f"indexed {n} nodes in {time.monotonic() - t0:.0f}s (model={EMBED_MODEL})")
probe = semantic_top_k("Ibuprofen 200mg tablets", top_k=3)
print("probe 'Ibuprofen 200mg tablets' ->", probe)
