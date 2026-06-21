"""Seed source-of-truth consistency.

Both seed paths (seed_products_from_txt + seed_demo_data) must pick the SAME canonical catalog file,
so demo results are identical regardless of which seeder ran (no "why are products missing?").
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(Path(rel)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_both_seeders_resolve_same_canonical_source():
    txt = _load("seed_txt_consistency", "scripts/seed_products_from_txt.py")
    demo = _load("seed_demo_consistency", "scripts/seed_demo_data.py")
    a = Path(str(txt._default_source())).name
    b = Path(str(demo._default_product_source())).name
    assert a == b, f"seed paths disagree: seed_products_from_txt={a} vs seed_demo_data={b}"
    assert a == "laptop-products-new-short.txt"  # the canonical expanded inventory


def test_canonical_source_exists():
    assert Path("docs/laptop-products-new-short.txt").exists()
