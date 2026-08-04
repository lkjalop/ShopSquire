"""Competitor price connector (Phase B) — fully OFFLINE tests on fixtures.

The cage under test: robots.txt honoured · JSON-LD is the only parse target · a page must MATCH our
product (brand + MPN/tokens) before an observation is written (a wrong match is worse than no match) ·
provenance labels · idempotent via record_observation dedup."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.connectors import competitor_price_fetch as cpf


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    s.execute(text("CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, price_cents INTEGER, active INTEGER DEFAULT 1)"))
    s.execute(text("INSERT INTO products (sku, name, price_cents) VALUES "
                   "('LAP-HP1','HP Laptop 15-fc0433AU 15.6\" FHD Laptop (Ryzen 5)[512GB]',95900)"))
    try:
        yield s
    finally:
        s.close()


def _page(title: str, price: str) -> str:
    return f"""<html><head><script type="application/ld+json">
    {{"@context":"https://schema.org","@type":"Product","name":"{title}",
      "offers":{{"@type":"Offer","price":"{price}","priceCurrency":"AUD"}}}}
    </script></head><body>x</body></html>"""


def _cfg(url="https://shop.example/p/hp-15"):
    return {"enabled": True, "user_agent": "TestBot/1.0", "min_request_interval_sec": 0,
            "timeout_sec": 5, "product_urls": {"LAP-HP1": {"shop.example": url}}}


# ── parsers ──────────────────────────────────────────────────────────────────
def test_jsonld_extraction_handles_graph_and_lists():
    graph = """<script type="application/ld+json">{"@graph":[{"@type":"BreadcrumbList"},
    {"@type":"Product","name":"X","offers":{"price":123.45}}]}</script>"""
    prods = cpf.extract_jsonld_products(graph)
    assert len(prods) == 1 and cpf.price_cents_from_product(prods[0]) == 12345


def test_price_parses_strings_dollars_and_low_price():
    assert cpf.price_cents_from_product({"offers": {"price": "1,199.00"}}) == 119900
    assert cpf.price_cents_from_product({"offers": [{"lowPrice": 899}]}) == 89900
    assert cpf.price_cents_from_product({"offers": {"price": "n/a"}}) is None


# ── the match guard ──────────────────────────────────────────────────────────
def test_exact_mpn_match_is_decisive():
    ok, reason = cpf.matches_our_product(
        "HP Laptop 15-fc0433AU 15.6\" FHD Laptop (Ryzen 5)[512GB]",
        "HP 15-fc0433AU 15.6in Ryzen 5 Notebook")
    assert ok and reason.startswith("mpn:")


def test_wrong_brand_or_series_only_is_refused():
    ok, _ = cpf.matches_our_product("HP Laptop 15-fc0433AU ...", "Lenovo IdeaPad Slim 3i 15.6\"")
    assert not ok                                        # brand mismatch
    ok2, _ = cpf.matches_our_product(
        "Lenovo IdeaPad 5 14\" 2K OLED 2-in-1 Laptop (Copilot+ PC)[512GB]",
        "Lenovo Yoga 7i 14\" WUXGA 2-in-1")               # same brand, different series
    assert not ok2                                       # below token threshold → refuse, don't guess


# ── robots ───────────────────────────────────────────────────────────────────
def test_robots_disallow_prefix_and_wildcard():
    txt = "User-agent: *\nDisallow: /checkout\nDisallow: /account\n"
    assert cpf.robots_allows(txt, "/p/hp-15", "TestBot/1.0") is True
    assert cpf.robots_allows(txt, "/checkout/pay", "TestBot/1.0") is False
    assert cpf.robots_allows(None, "/anything", "TestBot/1.0") is True     # no robots → allowed


# ── end-to-end offline ───────────────────────────────────────────────────────
def test_fetch_records_validated_observation_with_provenance(db):
    pages = {"https://shop.example/robots.txt": "User-agent: *\nDisallow: /cart\n",
             "https://shop.example/p/hp-15": _page("HP 15-fc0433AU Ryzen 5 Laptop", "899.00")}
    out = cpf.fetch_and_record(db, config=_cfg(), fetch_fn=lambda u: pages.get(u), sleep_fn=lambda s: None)
    assert out["recorded"] == 1 and out["skipped_match"] == 0
    row = db.execute(text("SELECT competitor, competitor_price_cents, source FROM competitor_observation")).fetchone()
    assert row[0] == "shop.example" and row[1] == 89900 and row[2] == "jsonld:shop.example"


def test_wrong_product_page_writes_nothing(db):
    from src.app.services.competitor_source import ensure_table
    ensure_table(db)   # nothing should be recorded, so create the table just to prove it stays empty
    pages = {"https://shop.example/robots.txt": None,
             "https://shop.example/p/hp-15": _page("Apple MacBook Air 13-inch M5", "1599.00")}
    out = cpf.fetch_and_record(db, config=_cfg(), fetch_fn=lambda u: pages.get(u), sleep_fn=lambda s: None)
    assert out["recorded"] == 0 and out["skipped_match"] == 1
    assert db.execute(text("SELECT COUNT(*) FROM competitor_observation")).scalar() == 0


def test_robots_disallow_skips_without_fetching(db):
    fetched = []
    def fetch(u):
        fetched.append(u)
        if u.endswith("robots.txt"):
            return "User-agent: *\nDisallow: /p\n"
        return _page("HP 15-fc0433AU", "899.00")
    out = cpf.fetch_and_record(db, config=_cfg(), fetch_fn=fetch, sleep_fn=lambda s: None)
    assert out["skipped_robots"] == 1 and out["recorded"] == 0
    assert all(u.endswith("robots.txt") for u in fetched)   # the product page was never requested


def test_disabled_config_is_a_noop(db):
    out = cpf.fetch_and_record(db, config={"enabled": False}, fetch_fn=lambda u: "x", sleep_fn=lambda s: None)
    assert out.get("disabled") is True and out["recorded"] == 0


def test_rerun_is_idempotent_same_observed_at(db):
    pages = {"https://shop.example/robots.txt": None,
             "https://shop.example/p/hp-15": _page("HP 15-fc0433AU", "899.00")}
    for _ in (1, 2):
        cpf.fetch_and_record(db, config=_cfg(), fetch_fn=lambda u: pages.get(u),
                             sleep_fn=lambda s: None, observed_at="2026-07-06T09:00:00")
    assert db.execute(text("SELECT COUNT(*) FROM competitor_observation")).scalar() == 1
