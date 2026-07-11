"""Cart-mutation resolver (V2 cart milestone step 1) — the model MAPS, the platform BINDS.

Covers the screenshot class directly: the compound edit that legacy sent to product search
('get rid of the HP Envy AND the ThinkPad, reduce the IdeaPad to 20'), the never-guess-then-wipe
ambiguity invariant, the closed-vocab clamp, and the empty-plan fall-through for non-cart turns.
The model is injected (llm_fn) so the doctrine is tested without a live Ollama.
"""
import json

from src.app.services.recommendation_core.cart_resolver import (
    CartMutationPlan,
    resolve_cart_mutation,
)
from src.app.services.recommendation_core.envelope import TurnEnvelope

# the exact cart from the 'still broken' screenshot (shot 25/27)
_CART = [
    {"sku": "LAP-A9A67AB9", "name": 'Lenovo ThinkPad L13 Gen 6 13.3" WUXGA AI PC Laptop', "quantity": 30},
    {"sku": "LAP-HPENVY01", "name": 'HP Envy x360 14-fc0189TU 14" WUXGA', "quantity": 1},
    {"sku": "LAP-IDEAP3I9", "name": 'Lenovo IdeaPad Slim 3i 15.3" 2K Laptop (Intel Core i7)[1TB]', "quantity": 1},
]


def _env(query, cart=_CART):
    return TurnEnvelope.from_suggest_params(query=query, uid="u1", tenant_id="t1", cart=cart)


def _fixed_llm(obj):
    """An llm_fn that returns a fixed JSON object regardless of prompt."""
    return lambda _prompt, _timeout: json.dumps(obj)


# ── the screenshot: a compound edit legacy sent to product search ────────────────

def test_compound_edit_binds_all_targets_to_skus():
    llm = _fixed_llm({
        "ops": [
            {"action": "remove_items", "targets": ["HP Envy", "Lenovo ThinkPad L13"]},
            {"action": "set_quantity", "targets": ["Lenovo IdeaPad Slim 3i"], "quantity": 20},
        ],
        "confidence": 0.9,
    })
    plan = resolve_cart_mutation(_env("get rid of the HP Envy and the ThinkPad, reduce the IdeaPad to 20"), llm_fn=llm)
    assert plan.source == "model"
    assert not plan.needs_clarification
    remove = next(o for o in plan.ops if o.action == "remove_items")
    setq = next(o for o in plan.ops if o.action == "set_quantity")
    assert set(remove.target_skus) == {"LAP-HPENVY01", "LAP-A9A67AB9"}
    assert setq.target_skus == ("LAP-IDEAP3I9",) and setq.quantity == 20


# ── whole-cart intents ──────────────────────────────────────────────────────────

def test_clear_all():
    plan = resolve_cart_mutation(_env("clear my cart"), llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}]}))
    assert [o.action for o in plan.ops] == ["clear_all"]
    assert plan.ops[0].target_skus == ()


def test_clear_previous():
    plan = resolve_cart_mutation(
        _env("clear the old items from my previous session"),
        llm_fn=_fixed_llm({"ops": [{"action": "clear_previous"}]}))
    assert [o.action for o in plan.ops] == ["clear_previous"]


def test_keep_only_binds_keeper():
    plan = resolve_cart_mutation(
        _env("clear the cart but keep the ThinkPad"),
        llm_fn=_fixed_llm({"ops": [{"action": "keep_only", "targets": ["the ThinkPad"]}]}))
    assert len(plan.ops) == 1 and plan.ops[0].action == "keep_only"
    assert plan.ops[0].target_skus == ("LAP-A9A67AB9",)


# ── the invariant: never guess-then-wipe ─────────────────────────────────────────

def test_unbound_name_is_ambiguous_not_guessed():
    plan = resolve_cart_mutation(
        _env("remove the Dell XPS"),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the Dell XPS"]}]}))
    assert plan.ops == ()                      # nothing removed — no Dell in cart
    assert plan.needs_clarification and "the Dell XPS" in plan.ambiguous


def test_generic_only_name_does_not_bind():
    # 'the laptop' overlaps all three lines ONLY on the generic 'laptop' token → no distinctive
    # match → ambiguous, never a random pick of one of three laptops.
    plan = resolve_cart_mutation(
        _env("remove the laptop"),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the laptop"]}]}))
    assert plan.ops == ()
    assert "the laptop" in plan.ambiguous


def test_tie_between_two_lines_is_ambiguous():
    cart = [
        {"sku": "MSI-1", "name": "MSI Modern 15 H AI Laptop", "quantity": 1},
        {"sku": "MSI-2", "name": "MSI Modern 15 H AI Laptop", "quantity": 1},
    ]
    plan = resolve_cart_mutation(
        _env("remove the MSI Modern 15", cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["MSI Modern 15"]}]}))
    assert plan.ops == () and "MSI Modern 15" in plan.ambiguous


# ── quantity clamps ──────────────────────────────────────────────────────────────

def test_set_quantity_zero_collapses_to_remove():
    plan = resolve_cart_mutation(
        _env("set the IdeaPad to 0"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 0}]}))
    assert len(plan.ops) == 1
    assert plan.ops[0].action == "remove_items" and plan.ops[0].target_skus == ("LAP-IDEAP3I9",)


def test_set_quantity_clamped_to_ceiling():
    plan = resolve_cart_mutation(
        _env("set the IdeaPad to 999999999"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 999999999}]}))
    assert plan.ops[0].action == "set_quantity" and plan.ops[0].quantity == 100_000


def test_set_quantity_without_number_is_dropped():
    plan = resolve_cart_mutation(
        _env("change the IdeaPad quantity"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": None}]}))
    assert plan.is_empty


# ── closed vocab + degradation ───────────────────────────────────────────────────

def test_unknown_action_dropped():
    plan = resolve_cart_mutation(
        _env("do a barrel roll"),
        llm_fn=_fixed_llm({"ops": [{"action": "frobnicate", "targets": ["ThinkPad"]}]}))
    assert plan.is_empty


def test_non_cart_intent_yields_empty_plan():
    # a product search — the model returns no ops → caller falls through to legacy
    plan = resolve_cart_mutation(_env("show me gaming laptops under $1500"), llm_fn=_fixed_llm({"ops": []}))
    assert plan.is_empty and plan.source == "default"


def test_bad_json_is_empty_plan_not_raise():
    plan = resolve_cart_mutation(_env("clear my cart"), llm_fn=lambda p, t: "not json {{{")
    assert plan is CartMutationPlan() or plan.is_empty
    assert plan.source == "default"


def test_empty_query_short_circuits():
    assert resolve_cart_mutation(_env(""), llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}]})).is_empty


def test_direct_sku_reference_binds():
    plan = resolve_cart_mutation(
        _env("remove LAP-HPENVY01"),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["LAP-HPENVY01"]}]}))
    assert plan.ops[0].target_skus == ("LAP-HPENVY01",)
