"""Phase 4 step 2: evidence (tenant-scoped, budget-in-cents, degrade-on-error) and fit
(tri-state verdicts, unknown-honesty, closest-match) — the last stops before the brain."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.evidence import (
    degraded_response,
    gather_evidence,
    refusal_allowed,
)
from src.app.services.recommendation_core.fit import build_cards, variant_attributes
from src.app.services.catalog_read_model import VariantView


@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', image_url TEXT, specs TEXT, "
        "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p1','LAP-1','MSI Thin 15in FHD 144Hz Gaming Laptop',169900,"
        "'{\"ram_gb\": 8, \"gpu_vram_gb\": 4}','MSI'), "
        "('p2','LAP-2','Asus TUF 16in 165Hz Gaming Laptop',209900,"
        "'{\"ram_gb\": 16, \"gpu_vram_gb\": 8}','Asus'), "
        "('p3','LAP-3','Mystery Laptop',99900,'{}','Acme')"))
    yield s
    s.close()


def _env(**over):
    kw = dict(query="gaming laptop", uid="u1", tenant_id="default")
    kw.update(over)
    return TurnEnvelope.from_suggest_params(**kw)


# ── evidence ──────────────────────────────────────────────────────────────────

def test_gather_evidence_budget_in_cents(db):
    b = gather_evidence(db, _env(budget_max=1800), text_query="laptop", mode="legacy")
    assert {v.sku for v in b.variants} == {"LAP-1", "LAP-3"}   # LAP-2 over $1800
    assert b.budget_filtered == 1 and b.total_before_budget == 3
    assert b.grounding in ("grounded", "empty")                # sqlite fixture has no sold set


def test_gather_evidence_never_raises_and_degrades():
    b = gather_evidence(None, _env())
    assert b.count == 0 and b.grounding == "error"
    resp = degraded_response(_env(), reason="db_unavailable")
    assert resp.degraded and resp.products == [] and "won't guess" in resp.message


def test_ungrounded_tenant_short_circuits_before_model(db):
    # M1.1: an un-onboarded tenant (no sold_taxonomy) must degrade WITHOUT a model call and
    # WITHOUT silent text-search garbage — grounding preserved as 'empty' for the facade/telemetry.
    from src.app.services.recommendation_core.core import recommend_turn
    called = {"model": False}
    def spy(p, t):
        called["model"] = True
        return "{}"
    r = recommend_turn(db, _env(), llm_fn=spy)   # db fixture has NO sold_taxonomy rows
    assert r.grounding == "empty" and r.degraded and r.products == []
    assert r.extras["degraded_reason"] == "catalog_not_onboarded"
    assert called["model"] is False              # short-circuited before the ~7s router call


def test_grounded_tenant_still_serves(db):
    from src.app.services.recommendation_core.core import recommend_turn
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")      # onboard the tenant
    import json
    r = recommend_turn(db, _env(query="laptop"),
                       llm_fn=lambda p, t: json.dumps({"lane": "SEARCH", "handle": "el-6-6",
                                                       "use_cases": [], "confidence": 0.9}))
    assert r.grounding == "grounded" and not r.degraded   # grounded path unaffected by M1.1


def test_refusal_allowed_only_on_explicit_false(db):
    from src.app.services.taxonomy_registry import add_sold_node
    assert refusal_allowed(db, "el-6-2") is False      # ungrounded tenant: None -> never refuse
    add_sold_node(db, node_handle="el-6-6")
    assert refusal_allowed(db, "el-6-2") is True       # grounded + not covered -> refusable
    assert refusal_allowed(db, "el-6-6") is False      # sold -> never
    assert refusal_allowed(db, "not-a-node") is False  # unknown -> never


# ── fit ───────────────────────────────────────────────────────────────────────

REQ = {"ram_gb": (">=", 16), "gpu_vram_gb": (">=", 8)}


def _views(db):
    return gather_evidence(db, _env(), text_query="laptop", mode="legacy").variants


def test_fit_ranking_meets_then_unknown_then_fails(db):
    cards, summary = build_cards(_views(db), REQ)
    assert [c.sku for c in cards] == ["LAP-2", "LAP-3", "LAP-1"]
    assert summary["meets"] == 1 and summary["unknown"] == 1 and summary["fails"] == 1
    assert not summary["closest_match_mode"]
    assert cards[0].why == ["meets all 2 requirements"]
    assert "unverified" in cards[1].why[0]              # unknown ≠ fail, shown and labeled
    assert "below requirement" in cards[2].why[0]


def test_fit_closest_match_mode_when_nothing_meets(db):
    cards, summary = build_cards(_views(db), {"ram_gb": (">=", 64)})
    assert summary["meets"] == 0 and summary["closest_match_mode"] is True
    assert cards                                        # never an empty grid (valorant fix)


def test_variant_attributes_specs_win_title_backfills():
    v = VariantView(sku="X", title="Something 240Hz 17in", specs={"refresh_hz": 165})
    attrs = variant_attributes(v)
    assert attrs["refresh_hz"] == 165                   # structured beats marketing copy
    assert attrs["display_in"] == 17                    # but the title fills gaps


def test_no_requirements_means_price_ranked_no_verdicts(db):
    cards, summary = build_cards(_views(db))
    assert [c.sku for c in cards] == ["LAP-3", "LAP-1", "LAP-2"]
    assert all(c.fit is None for c in cards) and summary["closest_match_mode"] is False
