"""brand_sql_predicate is PER-REQUEST profile-scoped — Phase 2A P0.

The brand -> SQL WHERE-fragment mapping is ADAPTER data resolved from the active StoreProfile's
`brand_sql_patterns` slot (electronics carries the verbatim predicates; other verticals derive a
name-LIKE predicate from their `manufacturers`). An electronics brand under a non-electronics
tenant yields no predicate (empty string = no bleed).

SECURITY: these fragments are interpolated into SQL, but no user input reaches them — the caller
normalises `brand` to a key and looks up a fixed/derived string from TRUSTED config.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import recommend_candidate_classify as cc


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    cc.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        cc.reset_cache()


def test_electronics_brand_predicates():
    with _vertical("electronics"):
        assert "macbook" in cc.brand_sql_predicate("apple").lower()
        assert "thinkpad" in cc.brand_sql_predicate("lenovo").lower()
        # the OS "windows" pseudo-brand excludes apple
        assert "not like" in cc.brand_sql_predicate("windows").lower()
        assert cc.brand_sql_predicate("nosuchbrand") == ""


def test_fashion_derives_from_manufacturers_no_bleed():
    with _vertical("fashion"):
        nike = cc.brand_sql_predicate("nike")
        assert "nike" in nike.lower() and "p.name" in nike
        assert nike.count("'%nike%'") == 1  # deduped (name == alias)
        # electronics brands must not resolve under a fashion tenant
        assert cc.brand_sql_predicate("apple") == ""
        assert cc.brand_sql_predicate("lenovo") == ""


def test_pharmacy_no_electronics_brand_bleed():
    with _vertical("pharmacy"):
        assert cc.brand_sql_predicate("apple") == ""
        assert cc.brand_sql_predicate("asus") == ""


def test_no_user_input_interpolation_safety():
    # a malicious "brand" string is normalised to a key and never appears in output —
    # an unknown key returns empty, so injection text cannot reach the SQL.
    with _vertical("electronics"):
        assert cc.brand_sql_predicate("apple'; DROP TABLE products;--") == ""
