"""Duplicate-SKU collapse: the same product under multiple SKUs becomes one card,
genuinely different configs are preserved."""
from __future__ import annotations

from src.app.services.sku_canonicalize import canonicalize, duplicate_skus


def test_collapses_same_product_under_two_skus_keeping_richer_record():
    rows = [
        {"sku": "LP021", "name": 'MSI Thin A15 15" FHD 144Hz Gaming Laptop (Ryzen 5)',
         "specs": {"gpu": "?", "ram_gb": 8}, "score": 50, "stock": 3, "price_cents": 179900},
        {"sku": "LAP-0020", "name": 'MSI Thin A15 15" FHD 144Hz Gaming Laptop (Ryzen 5)',
         "specs": {"gpu": "GeForce RTX 3050", "ram_gb": 8, "refresh_hz": 144}, "score": 50,
         "stock": 5, "price_cents": 179900},
    ]
    out = canonicalize(rows)
    assert len(out) == 1
    # Keeps the record with the more complete specs (LAP-0020 has the real GPU).
    assert out[0]["sku"] == "LAP-0020"


def test_preserves_distinct_configs():
    rows = [
        {"sku": "A", "name": "Dell 15 (8GB)", "specs": {"ram_gb": 8}, "score": 10},
        {"sku": "B", "name": "Dell 15 (16GB)", "specs": {"ram_gb": 16}, "score": 10},
    ]
    out = canonicalize(rows)
    assert len(out) == 2


def test_case_and_whitespace_insensitive_identity():
    rows = [
        {"sku": "X", "name": "Dell  Inspiron   15", "specs": {}, "score": 5, "stock": 0, "price_cents": 90000},
        {"sku": "Y", "name": "dell inspiron 15", "specs": {}, "score": 9, "stock": 1, "price_cents": 90000},
    ]
    out = canonicalize(rows)
    assert len(out) == 1
    # Tie on specs -> higher score wins (Y).
    assert out[0]["sku"] == "Y"


def test_rows_without_name_pass_through():
    rows = [{"sku": "Z", "specs": {}}, {"sku": "Z2", "specs": {}}]
    assert len(canonicalize(rows)) == 2


def test_duplicate_skus_diagnostic():
    rows = [
        {"sku": "LP021", "name": "MSI Thin A15"},
        {"sku": "LAP-0020", "name": "MSI Thin A15"},
        {"sku": "U1", "name": "Unique Laptop"},
    ]
    dups = duplicate_skus(rows)
    assert "msi thin a15" in dups
    assert set(dups["msi thin a15"]) == {"LP021", "LAP-0020"}
    assert "unique laptop" not in dups
