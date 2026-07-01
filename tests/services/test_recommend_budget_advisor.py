"""recommend_budget_advisor service — the extracted budget/brand advisor stage (core/adapter).

CORE: deterministic, price-grounded budget/brand verdicts + assistant message. Pure builders.
Parity: the router re-exports these (same objects), behaviour unchanged after extraction.
"""
from __future__ import annotations

from src.app.services.recommend_budget_advisor import (
    _USE_CASE_BUDGET_FLOORS,
    _assess_budget_fitness,
    _budget_reasoning_requested,
    _build_brand_budget_answer,
    _build_brand_budget_answer_v2,
    _build_budget_reasoning_note,
    _build_minimum_recommended_tiers,
    _deterministic_assistant_message,
    _persona_summary_label,
)


def _rows(*prices):
    return [{"name": f"Laptop {i}", "price_cents": int(p * 100)} for i, p in enumerate(prices)]


def test_budget_reasoning_requested():
    assert _budget_reasoning_requested("is $1800 enough for gaming?") is True
    assert _budget_reasoning_requested("why should I go higher on budget?") is True
    assert _budget_reasoning_requested("show me some laptops") is False
    assert _budget_reasoning_requested("") is False


def test_assess_budget_fitness_low_high_unknown():
    low = _assess_budget_fitness("gaming_aaa_heavy", None, 200)
    assert low["status"] == "low"
    high = _assess_budget_fitness("gaming_aaa_heavy", None, 99999)
    assert high["status"] == "high"
    assert _assess_budget_fitness(None, None, 1500)["status"] == "unknown"
    assert _assess_budget_fitness("gaming_aaa_heavy", None, None)["status"] == "unknown"


def test_assess_budget_fitness_uses_active_profile_without_cross_vertical_fallback():
    from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id

    token = set_active_profile_id("pharmacy")
    try:
        low = _assess_budget_fitness("pain_relief", None, 2)
        assert low["status"] == "low"
        assert "laptop" not in str(low.get("advice") or "").lower()
        assert _assess_budget_fitness("gaming_aaa_heavy", None, 2000)["status"] == "unknown"
    finally:
        reset_active_profile_id(token)


def test_persona_summary_label():
    assert _persona_summary_label(None, "gaming") == "gaming"
    assert _persona_summary_label(None, "office_finance") == "finance work"
    assert _persona_summary_label("gamer", "office_unknown_x") == "office work"  # startswith office_
    assert _persona_summary_label(None, "nonsense") == ""


def test_build_minimum_recommended_tiers_splits():
    out = _build_minimum_recommended_tiers(
        _rows(700, 900, 1500), budget_min=None, budget_max=None, use_case="gaming_aaa_heavy"
    )
    assert isinstance(out["minimum"], list) and isinstance(out["recommended"], list)
    assert "show_split" in out


def test_brand_budget_answer_v2_generic_yes_no():
    yes = _build_brand_budget_answer_v2(
        "is $2000 enough?", _rows(1200, 1500), {"budget_max": 2000}
    )
    assert yes.startswith("Yes")
    short = _build_brand_budget_answer_v2(
        "is $600 enough?", _rows(1200, 1500), {"budget_max": 600}
    )
    assert short.startswith("No")
    # not a budget question → empty
    assert _build_brand_budget_answer_v2("show me laptops", _rows(1200), {}) == ""


def test_brand_budget_answer_brand_path():
    ans = _build_brand_budget_answer(
        "is $2500 enough for apple?",
        [{"name": "MacBook Pro 14", "price_cents": 240000}],
        {"budget_max": 2500},
    )
    assert "Apple" in ans


def test_deterministic_message_recovery_on_empty():
    msg = _deterministic_assistant_message("any gaming laptop under $500", [], {"budget_max": 500})
    assert msg and "couldn't find" in msg.lower()


def test_deterministic_message_with_results():
    msg = _deterministic_assistant_message(
        "gaming laptop", _rows(1200, 1500), {"budget_max": 2000, "use_case": "gaming"}
    )
    assert msg and "found" in msg.lower()


def test_deterministic_message_is_paragraphed_not_one_blob():
    # the buyer chat splits on blank lines — the verdict, the picks, and the follow-up question must
    # land on separate paragraphs so the reply doesn't render as one wall of text (screenshot #008).
    msg = _deterministic_assistant_message(
        "gaming laptop", _rows(1200, 1500), {"budget_max": 2000, "use_case": "gaming"}
    )
    paras = [p for p in msg.split("\n\n") if p.strip()]
    assert len(paras) >= 2, msg                      # at least verdict + follow-up as distinct paras
    assert paras[-1].strip().endswith("?"), msg      # the follow-up question is its own final paragraph


def test_build_budget_reasoning_note_gated():
    # not requested → empty
    assert _build_budget_reasoning_note("show me laptops", _rows(1200), {"budget_max": 1500}) == ""


def test_use_case_budget_floors_shape():
    assert _USE_CASE_BUDGET_FLOORS["gaming_aaa_heavy"] == 1200
    assert isinstance(_USE_CASE_BUDGET_FLOORS, dict)


def test_router_reexports_same_objects():
    from src.app.routers import recommend as r

    assert r._build_brand_budget_answer is _build_brand_budget_answer
    assert r._build_brand_budget_answer_v2 is _build_brand_budget_answer_v2
    assert r._deterministic_assistant_message is _deterministic_assistant_message
    assert r._assess_budget_fitness is _assess_budget_fitness
    assert r._build_minimum_recommended_tiers is _build_minimum_recommended_tiers
    assert r._build_budget_reasoning_note is _build_budget_reasoning_note
    assert r._budget_reasoning_requested is _budget_reasoning_requested
    assert r._persona_summary_label is _persona_summary_label
    assert r._USE_CASE_BUDGET_FLOORS is _USE_CASE_BUDGET_FLOORS
