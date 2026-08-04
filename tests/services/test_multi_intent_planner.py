"""Multi-intent planner — decompose → amend prior qty → scatter-gather new lines → guard. Agnostic, pure."""
from __future__ import annotations

from src.app.services.multi_intent_planner import plan_turn

SCENARIO = ("nah that's too expensive, actually i need 15 instead? what options for headsets and "
            "hard drives. i have a budget for 1200 for those?")

_CATALOG = {
    "headsets": [{"name": "SteelSeries Gaming Headset", "price_cents": 12900}],
    "hard drives": [{"name": "Samsung 2TB Hard Drive", "price_cents": 9900}],
}


def _good_search(category, budget_max):
    rows = _CATALOG.get(category, [])
    return [r for r in rows if budget_max is None or (r["price_cents"] / 100) <= budget_max]


def _laptop_prior():
    return [{"ref": "LAP-1", "category": "laptops", "requested_qty": 20,
             "results": [{"name": "MSI Katana Laptop", "price_cents": 180000}]}]


def test_full_scenario_end_to_end():
    out = plan_turn(SCENARIO, prior_lines=_laptop_prior(), search_fn=_good_search)
    plan = out["plan"]
    # prior laptop kept, quantity AMENDED 20 → 15, still $1800 context (no scoped budget on it)
    lap = next(l for l in plan if l.get("ref") == "LAP-1")
    assert lap["requested_qty"] == 15 and lap["scope"] == "prior" and lap.get("budget_max") is None
    # NEW lines fanned out with the SCOPED $1200, results within budget
    cats = {l["category"] for l in plan if l["scope"] == "new"}
    assert "headsets" in cats and any("drive" in c for c in cats)
    assert all(l["budget_max"] == 1200 for l in plan if l["scope"] == "new")
    # verified clean, but a mixed money-changing turn → confirm; price objection → value angle
    assert out["verdict"]["ok"] is True
    assert out["needs_confirmation"] is True
    assert out["objection_angle"] == "value"


def test_guard_catches_bad_fanout():
    # a search that returns a LAPTOP for a headset line → category mismatch → not ok → confirm
    def _bad_search(category, budget_max):
        return [{"name": "Some Laptop", "price_cents": 90000}]
    out = plan_turn("what options for headsets and cables for 1200 for those",
                    prior_lines=_laptop_prior(), search_fn=_bad_search)
    assert out["verdict"]["ok"] is False
    assert any("category mismatch" in v for v in out["verdict"]["violations"])
    assert out["needs_confirmation"] is True


def test_context_survival_enforced():
    # the laptop prior MUST survive; the planner always carries it → guard passes on survival
    out = plan_turn("what headsets for 1200 for those", prior_lines=_laptop_prior(), search_fn=_good_search)
    assert any(l.get("ref") == "LAP-1" for l in out["plan"])
    assert not any("context lost" in v for v in out["verdict"]["violations"])


def test_no_prior_selection_amendment_becomes_a_note_not_a_wrong_qty():
    out = plan_turn("actually make it 15 instead", prior_lines=None, search_fn=_good_search)
    # no prior item → the amendment is a note, not a silent qty change; nothing to amend
    assert out["intents"]["amendments"] == []
    assert any("no prior selection" in n for n in out["intents"]["notes"])


def test_bare_qty_amendment_targets_the_line_that_actually_changes():
    """cart = [Lenovo 25, Apple 15]; a bare 'make it 15' must amend LENOVO (the line whose qty
    changes), NOT blindly the LAST line (Apple, already 15 → wrong laptop + no-op). Regression for
    the demo screenshot where 'make it 15' amended the Apple line."""
    prior = [
        {"ref": "LAP-LENOVO", "category": "laptops", "requested_qty": 25,
         "results": [{"name": "Lenovo IdeaPad", "price_cents": 159900}]},
        {"ref": "LAP-APPLE", "category": "laptops", "requested_qty": 15,
         "results": [{"name": "Apple MacBook Air", "price_cents": 179900}]},
    ]
    out = plan_turn("actually make it 15 instead", prior_lines=prior, search_fn=_good_search)
    amended = [l for l in out["plan"] if l.get("amended")]
    assert len(amended) == 1, f"exactly one line amended, got {amended}"
    assert amended[0]["ref"] == "LAP-LENOVO", "must target the changing line, not the last"
    assert amended[0]["requested_qty"] == 15
    # Apple line carried forward UNCHANGED (not spuriously marked amended)
    apple = next(l for l in out["plan"] if l.get("ref") == "LAP-APPLE")
    assert not apple.get("amended") and apple["requested_qty"] == 15


def test_bare_qty_amendment_falls_back_to_last_when_all_match():
    """If every prior line already equals the requested qty, keep the old behavior (amend the last)."""
    prior = [{"ref": "A", "category": "laptops", "requested_qty": 15},
             {"ref": "B", "category": "laptops", "requested_qty": 15}]
    out = plan_turn("actually make it 15 instead", prior_lines=prior, search_fn=_good_search)
    amended = [l for l in out["plan"] if l.get("amended")]
    assert len(amended) == 1 and amended[0]["ref"] == "B"  # last line


# ── named-ref resolution + removals (the compound cart-op) ──
def _three_line_cart():
    return [
        {"ref": "SKU-HP", "name": 'HP Envy x360 14" WUXGA 2-in-1 Laptop', "requested_qty": 25, "category": "laptops"},
        {"ref": "SKU-TP", "name": 'Lenovo ThinkPad L13 Gen 6 13.3" Laptop', "requested_qty": 30, "category": "laptops"},
        {"ref": "SKU-IP", "name": 'Lenovo IdeaPad Slim 3i 15.3" 2K Laptop', "requested_qty": 40, "category": "laptops"},
    ]


def test_compound_removals_and_named_qty_resolve_to_the_right_lines():
    from src.app.services.multi_intent_planner import plan_turn
    out = plan_turn('get rid of the HP Envy and the ThinkPad L13, reduce the IdeaPad Slim to 20',
                    prior_lines=_three_line_cart(), search_fn=lambda c, b: [])
    by_ref = {l["ref"]: l for l in out["plan"] if l.get("scope") == "prior"}
    assert by_ref["SKU-HP"]["amended"] and by_ref["SKU-HP"]["requested_qty"] == 0
    assert by_ref["SKU-TP"]["amended"] and by_ref["SKU-TP"]["requested_qty"] == 0
    assert by_ref["SKU-IP"]["amended"] and by_ref["SKU-IP"]["requested_qty"] == 20
    assert out["verdict"]["ok"], out["verdict"]         # guard allows qty-0 ONLY as an amended removal
    assert not out["warnings"]


def test_unmatched_named_ref_warns_and_never_guesses():
    from src.app.services.multi_intent_planner import plan_turn
    out = plan_turn("remove the macbook pro", prior_lines=_three_line_cart(), search_fn=lambda c, b: [])
    assert any("couldn't match" in w for w in out["warnings"])
    assert not [l for l in out["plan"] if l.get("amended")]      # nothing touched
    assert out["needs_confirmation"] is True                      # warning forces the card


def test_ambiguous_ref_is_not_applied():
    # "the Lenovo" matches BOTH Lenovo lines equally → tie → warn, don't pick one
    from src.app.services.multi_intent_planner import plan_turn
    out = plan_turn("remove the lenovo", prior_lines=_three_line_cart(), search_fn=lambda c, b: [])
    assert not [l for l in out["plan"] if l.get("amended")]
    assert any("couldn't match" in w for w in out["warnings"])


# ── R5: embedding fallback for paraphrase refs (flag-gated, fail-safe preserved) ──

def test_semantic_fallback_off_by_default(monkeypatch):
    monkeypatch.delenv("MULTI_INTENT_SEMANTIC_REF_ENABLED", raising=False)
    from src.app.services.multi_intent_planner import _resolve_named_ref
    prior = [{"name": "Alpha X1 Gaming 16", "requested_qty": 2},
             {"name": "Beta Pro 14", "requested_qty": 1}]
    # no shared distinctive token AND flag off -> None (ask the human), exactly as before
    assert _resolve_named_ref("the cheap one", prior) is None


def test_semantic_fallback_binds_clear_winner(monkeypatch):
    monkeypatch.setenv("MULTI_INTENT_SEMANTIC_REF_ENABLED", "1")
    import src.app.services.multi_intent_planner as mip
    import src.app.services.embeddings as emb
    # deterministic fake embeddings: "the gaming machine" ≈ line 0
    vecs = {"the gaming machine": [1.0, 0.0], "Alpha X1 Gaming 16": [0.98, 0.2], "Beta Office 14": [0.0, 1.0]}
    monkeypatch.setattr(emb, "embed_text_dense", lambda t: (vecs.get(t, [0.5, 0.5]), "fake"))
    prior = [{"name": "Alpha X1 Gaming 16"}, {"name": "Beta Office 14"}]
    assert mip._resolve_named_ref("the gaming machine", prior) == 0


def test_semantic_fallback_ambiguous_stays_none(monkeypatch):
    monkeypatch.setenv("MULTI_INTENT_SEMANTIC_REF_ENABLED", "1")
    import src.app.services.multi_intent_planner as mip
    import src.app.services.embeddings as emb
    monkeypatch.setattr(emb, "embed_text_dense", lambda t: ([1.0, 0.0], "fake"))  # everything identical
    prior = [{"name": "Alpha X1"}, {"name": "Alpha X2"}]
    assert mip._resolve_named_ref("the newer machine", prior) is None   # no margin -> ask, don't guess


def test_semantic_fallback_embeddings_down_is_safe(monkeypatch):
    monkeypatch.setenv("MULTI_INTENT_SEMANTIC_REF_ENABLED", "1")
    import src.app.services.multi_intent_planner as mip
    import src.app.services.embeddings as emb
    def boom(t):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(emb, "embed_text_dense", boom)
    assert mip._resolve_named_ref("the shiny one", [{"name": "Alpha X1"}]) is None
