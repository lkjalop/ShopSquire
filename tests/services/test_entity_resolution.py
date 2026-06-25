"""Unit tests for the agnostic entity-resolution core (services/entity_resolution.py).

Pure resolvers with injected alias/catalog data — the canonicalization the hippograph dedupes
nodes on. No app/DB deps (the *_for_profile wrapper is exercised separately/lightly).
"""
from __future__ import annotations

from src.app.services import entity_resolution as er
from src.app.services.entity_resolution import EntityRef


# ── normalize ────────────────────────────────────────────────────────────────
def test_normalize_label_collapses_case_punct_space():
    assert er.normalize_label("  Dell,  XPS!! ") == "dell xps"
    assert er.normalize_label(None) == ""


# ── brand resolution ─────────────────────────────────────────────────────────
def test_brand_exact_canonical_high_confidence():
    r = er.resolve_brand("Dell", known=["dell", "apple"])
    assert r and r.kind == "brand" and r.id == "dell" and r.confidence == 1.0


def test_brand_variants_collapse_to_same_id():
    a = er.resolve_brand("Dell", known=["dell"])
    b = er.resolve_brand("DELL", known=["dell"])
    c = er.resolve_brand("  dell ", known=["dell"])
    assert a.id == b.id == c.id == "dell"  # the whole point: one node


def test_brand_alias_maps_to_canonical():
    r = er.resolve_brand("hp", alias_map={"hp": "hewlett packard"}, known=["hewlett packard"])
    assert r.id == "hewlett_packard" and r.confidence == 0.95


def test_brand_token_level_alias():
    r = er.resolve_brand("dell xps 13", known=["dell"])
    assert r.id == "dell" and r.confidence == 0.7


def test_brand_unknown_still_canonicalizes_low_confidence():
    r = er.resolve_brand("AcmeCorp", known=["dell"])
    assert r.id == "acmecorp" and r.confidence == 0.6


def test_brand_empty_is_none():
    assert er.resolve_brand("   ") is None


# ── product resolution ───────────────────────────────────────────────────────
def test_product_known_sku_is_canonical():
    r = er.resolve_product("GAM-0002", catalog_skus=["GAM-0002", "GAM-0004"])
    assert r.kind == "product" and r.id == "GAM-0002" and r.confidence == 1.0


def test_product_sku_pattern_match():
    r = er.resolve_product("ABC-1234", sku_pattern=r"[A-Z]+-\d+")
    assert r.id == "ABC-1234" and r.confidence == 0.9


def test_product_name_node_namespaced():
    r = er.resolve_product("MacBook Air 13")
    assert r.id.startswith("name:") and r.confidence == 0.5  # never collides with a real sku


# ── user resolution (PII-safe) ───────────────────────────────────────────────
def test_user_already_hashed_used_as_is():
    r = er.resolve_user("abc123hash", already_hashed=True)
    assert r.kind == "user" and r.id == "abc123hash" and r.raw == "<hashed>"


def test_user_raw_is_hashed_and_redacted():
    r = er.resolve_user("alice@example.com", salt="s")
    assert r.raw == "<pii-redacted>"  # never store raw PII
    assert r.id != "alice@example.com" and len(r.id) == 32
    # deterministic: same input+salt → same id (stable node)
    assert er.resolve_user("alice@example.com", salt="s").id == r.id


# ── dispatcher ───────────────────────────────────────────────────────────────
def test_canonical_entity_dispatch():
    assert er.canonical_entity("brand", "Dell", known=["dell"]).id == "dell"
    assert er.canonical_entity("product", "X-1", sku_pattern=r"X-\d").id == "X-1"
    assert er.canonical_entity("user", "h", already_hashed=True).kind == "user"
    assert er.canonical_entity("unknown", "x") is None


# ── profile-backed wrapper (light; tolerant if profile API shifts) ───────────
def test_resolve_brand_for_profile_returns_ref_or_none():
    r = er.resolve_brand_for_profile("Dell")
    assert r is None or isinstance(r, EntityRef)
