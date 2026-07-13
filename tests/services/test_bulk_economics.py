"""Phase 1f — bulk-order economics: quantity × per-unit floor vs total budget → viability + the
tradeoff menu (increase budget / reduce units / bundle-fit / payment plan)."""
from src.app.services.recommendation_core.bulk import assess_bulk


def test_fits_within_budget():
    e = assess_bulk(20, 3_000_000, 100_000)          # 20 × $1000 = $20k ≤ $30k
    assert e["verdict"] == "fits" and e["needed_cents"] == 2_000_000 and not e["tradeoffs"]


def test_over_budget_offers_the_menu():
    e = assess_bulk(20, 1_600_000, 112_400)          # 20 × $1124 = $22,480 > $16,000
    assert e["verdict"] == "over_budget"
    assert e["per_unit_cents"] == 80_000             # $16,000 / 20 = $800/unit
    assert e["units_affordable"] == 14               # 1,600,000 // 112,400
    ids = {t["id"] for t in e["tradeoffs"]}
    assert {"increase_budget", "reduce_units", "financing_review"} <= ids


def test_bundle_makes_it_fit():
    # cheaper hybrid floor $708 (laptop $629 + tablet $79) × 20 = $14,160 ≤ $16,000 → fits
    e = assess_bulk(20, 1_600_000, 112_400, bundle_floor_cents=70_800)
    assert e["bundle"]["fits"] is True and e["bundle"]["needed_cents"] == 1_416_000
    assert any(t["id"] == "bundle" and t["fits"] for t in e["tradeoffs"])


def test_unsized_without_budget():
    e = assess_bulk(20, None, 112_400)
    assert e["verdict"] == "unsized" and e["per_unit_cents"] is None and not e["tradeoffs"]


def test_no_quantity_or_floor_returns_none():
    assert assess_bulk(0, 1_600_000, 100_000) is None
    assert assess_bulk(20, 1_600_000, None) is None


def test_resolve_bulk_total_never_treats_per_unit_as_total():
    """Review-10 P0 arithmetic-safety: budget_scope decides; a per-unit budget is NEVER a total."""
    from types import SimpleNamespace
    from src.app.services.recommendation_core.core import _resolve_bulk_total
    from src.app.services.recommendation_core.envelope import TurnEnvelope

    def env(bmax):
        return TurnEnvelope.from_suggest_params(query="x", uid="u", tenant_id="default", budget_max=bmax)

    def dec(scope, total=None):
        return SimpleNamespace(budget_scope=scope, total_budget_cents=total)

    # env() takes DOLLARS (from_suggest_params converts →cents); expectations are in CENTS.
    assert _resolve_bulk_total(dec("unknown", total=1_600_000), env(None), 20) == (1_600_000, False)  # explicit total wins
    assert _resolve_bulk_total(dec("per_unit"), env(1900), 25) == (190_000 * 25, False)   # $1900 each × 25
    assert _resolve_bulk_total(dec("total"), env(16000), 20) == (1_600_000, False)        # $16000 tagged total
    assert _resolve_bulk_total(dec("unknown"), env(16000), 20) == (None, True)            # AMBIGUOUS → ask
    assert _resolve_bulk_total(dec("unknown"), env(None), 20) == (None, False)            # no budget → unsized
