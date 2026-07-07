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


# ── capability yes/no verdicts ("can it run X", "good for Y") — answer-first from the top result's specs ──
_GPU = [{"name": "Asus TUF Gaming F15 RTX 4060", "specs": {"gpu_discrete": True, "gpu": "RTX 4060", "ram_gb": 16}}]
_IGPU16 = [{"name": "Lenovo ThinkPad T14", "specs": {"gpu_discrete": False, "ram_gb": 16}}]
_IGPU8 = [{"name": "Acer Aspire 3", "specs": {"gpu_discrete": False, "ram_gb": 8}}]


def test_capability_gaming_verdict_by_gpu():
    from src.app.services.recommend_budget_advisor import _build_capability_answer as cap
    assert cap("can it run valorant?", _GPU).lower().startswith("yes")
    # integrated GPU → honest hedge, not a false yes, and offers the discrete-GPU alternative
    hedge = cap("can it run cyberpunk?", _IGPU16).lower()
    assert "integrated" in hedge and "dedicated" in hedge


def test_capability_heavy_and_dev_and_light():
    from src.app.services.recommend_budget_advisor import _build_capability_answer as cap
    assert cap("good for 4k rendering?", _GPU).lower().startswith("yes")
    assert "light" in cap("is this good for video editing?", _IGPU16).lower()   # integrated → not suited
    assert cap("is it good for coding?", _IGPU16).lower().startswith("yes")      # 16GB ok for dev
    assert "16gb" in cap("good for coding?", _IGPU8).lower()                     # 8GB → recommend more
    assert cap("good for office work and browsing?", _IGPU16).lower().startswith("yes")


def test_capability_returns_empty_for_non_capability_or_budget_turns():
    from src.app.services.recommend_budget_advisor import _build_capability_answer as cap, _build_brand_budget_answer_v2 as v2
    assert cap("gaming laptop under 2000", _GPU) == ""     # a search, not a capability question
    assert cap("hello", _GPU) == ""
    assert cap("can it run valorant?", []) == ""            # no results → no verdict
    # v2 still answers budget questions (capability path must not shadow the budget path)
    assert v2("is 1800 enough for gaming?", _GPU, {"budget_max": 1800}).lower().startswith(("yes", "no"))


# ── 2026-07-07 "not smart" fixes: VRAM-aware verdicts + catalog-aware go-higher ──

def _r(name, price, vram=None, ram=None, gpu=True):
    specs = {"gpu_discrete": gpu}
    if vram: specs["gpu_vram_gb"] = vram
    if ram: specs["ram_gb"] = ram
    return {"name": name, "price_cents": price * 100, "specs": specs}


def test_heavy_verdict_low_vram_hedges_honestly():
    from src.app.services.recommend_budget_advisor import _build_capability_answer
    ans = _build_capability_answer("would it be good for training llm models?",
                                   [_r("Alpha X1", 1199, vram=8, ram=16)])
    assert "Partly" in ans and "8GB" in ans and "16GB+" in ans   # names the limit AND the bar


def test_heavy_verdict_high_vram_confident_yes():
    from src.app.services.recommend_budget_advisor import _build_capability_answer
    ans = _build_capability_answer("good for training large models?",
                                   [_r("Omega Max", 5999, vram=24, ram=64)])
    assert ans.startswith("Yes") and "24GB" in ans


def test_heavy_verdict_unknown_vram_keeps_legacy_heuristic():
    from src.app.services.recommend_budget_advisor import _build_capability_answer
    ans = _build_capability_answer("can it handle ml training?",
                                   [_r("Beta Pro", 1799, vram=None, ram=32)])
    assert ans.startswith("Yes")   # no vram data → old discrete+RAM behavior, no false hedge


def test_step_ups_come_from_catalog(monkeypatch):
    import src.app.services.recommend_budget_advisor as adv
    monkeypatch.setattr(adv, "_above_budget_step_ups",
                        lambda cap, mv: [("Omega Max 16 OLED Galaxy", 4499.0, 16), ("Titan Ultra", 5999.0, 24)])
    # drive the ok-status budget answer path
    constraints = {"use_case": "ai ml workstation", "budget_max": 3500,
                   "budget_fitness": {"status": "ok", "floor": 1500}}
    ans = adv._build_budget_reasoning_note("is 3500 enough? what if i go higher?",
                                           [_r("Alpha X1", 3499, vram=8, ram=32)], constraints)
    assert "real payoff" in ans and "16GB" in ans and "24GB" in ans
    assert "8GB GPU memory" in ans   # the honesty hedge for ai/ml at <16GB


# ── 2026-07-07 live-audit: VRAM defense vanished on the /chat path (text budget + id-drift use_case) ──

def test_budget_note_fires_with_text_budget_key():
    from src.app.services.recommend_budget_advisor import _build_budget_reasoning_note
    # /chat lands the budget in _request_budget_max, NOT budget_max — the note must still resolve it
    note = _build_budget_reasoning_note(
        "is 3500 enough for ml? what if i go higher?",
        [_r("Alpha", 3499, vram=8, ram=32)],
        {"use_case": "ai_ml_workstation", "_request_budget_max": 3500})
    assert note and "GPU memory" in note


def test_budget_fitness_resolves_use_case_id_drift():
    from src.app.services.recommend_budget_advisor import _assess_budget_fitness
    # "ml_ai" (planner id) must bind to the "ai_ml_workstation" floor key by token overlap
    assert _assess_budget_fitness("ml_ai", None, 3500).get("status") == "ok"
    assert _assess_budget_fitness("ai_ml_workstation", None, 3500).get("status") == "ok"


def test_budget_note_full_chat_path_has_vram_and_stepup():
    from src.app.services.recommend_budget_advisor import _build_budget_reasoning_note
    note = _build_budget_reasoning_note(
        "training llm models, is 3500 enough? if i go higher what then?",
        [_r("Alpha", 3499, vram=8, ram=32)],
        {"use_case": "ml_ai", "_request_budget_max": 3500})   # BOTH bugs at once (chat's real shape)
    assert note and "GPU memory" in note and "16GB+" in note


def test_budget_note_recomputes_over_stale_unknown_fitness():
    """The live /chat shape: budget_max set + canonical use_case, but budget_fitness pre-stored as
    {status: unknown} (computed too early upstream). The note must RECOMPUTE, not fall through to ''."""
    from src.app.services.recommend_budget_advisor import _build_budget_reasoning_note
    note = _build_budget_reasoning_note(
        "training llm models, is 3500 enough? if i go higher what then?",
        [_r("Alpha", 3499, vram=8, ram=32)],
        {"use_case": "ai_ml_workstation", "budget_max": 3500, "budget_fitness": {"status": "unknown"}})
    assert note and "GPU memory" in note
