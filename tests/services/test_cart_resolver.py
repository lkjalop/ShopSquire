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


def test_compound_action_question_uses_fast_grammar_and_answers_reconfirmation():
    cart = [{
        "sku": "LAP-DELL",
        "name": 'Dell DB16255 16" WUXGA Copilot+ PC Laptop',
        "quantity": 20,
    }]
    plan = resolve_cart_mutation(_env(
        "Actually reduce the Dell order to 15 and keep the same total budget. "
        "Do I need to reconfirm the supplier plan?",
        cart=cart,
    ))

    assert plan.source == "grammar"
    assert plan.confidence == 1.0
    assert plan.ops[0].action == "set_quantity"
    assert plan.ops[0].target_skus == ("LAP-DELL",)
    assert plan.ops[0].quantity == 15


def test_bare_quantity_continuation_binds_the_only_cart_line():
    cart = [{
        "sku": "LAP-MSI",
        "name": 'MSI Thin A15 15" Gaming Laptop',
        "quantity": 20,
    }]

    plan = resolve_cart_mutation(
        _env("Actually make it 15, and do I need to reconfirm the delivery plan?", cart=cart)
    )

    assert plan.source == "grammar"
    assert not plan.needs_clarification
    assert plan.ops[0].action == "set_quantity"
    assert plan.ops[0].target_skus == ("LAP-MSI",)
    assert plan.ops[0].quantity == 15


def test_bare_quantity_continuation_does_not_guess_across_cart_lines():
    plan = resolve_cart_mutation(_env("Actually make it 15"))

    assert not plan.ops
    assert plan.needs_clarification
    assert "__last__" in plan.ambiguous


def test_replacement_is_catalog_clamped_and_total_budget_sets_affordable_quantity():
    cart = [{"sku": "GAM-0006", "name": "Dell G16 Gaming Laptop", "quantity": 20}]
    catalog = lambda _tenant: [{  # noqa: E731 - injected finite catalog projection
        "sku": "LAP-PROART5070",
        "name": "ASUS ProArt 16 RTX 5070",
        "brand": "ASUS",
        "price_cents": 489400,
        "active": True,
    }]
    plan = resolve_cart_mutation(
        _env("Replace the Dell G16 with the ASUS ProArt 16 RTX 5070, but keep the total "
             "budget at $54,000. Adjust the quantity to the maximum affordable number.", cart=cart),
        llm_fn=_fixed_llm({"ops": [{
            "action": "replace_item",
            "targets": ["Dell G16"],
            "replacement": "ASUS ProArt 16 RTX 5070",
            "quantity_mode": "max_affordable",
        }], "confidence": 0.95}),
        catalog_candidates_fn=catalog,
    )

    assert not plan.ambiguous
    assert len(plan.ops) == 1
    op = plan.ops[0]
    assert op.action == "replace_item"
    assert op.target_skus == ("GAM-0006",)
    assert op.replacement_sku == "LAP-PROART5070"
    assert op.replacement_name == "ASUS ProArt 16 RTX 5070"
    assert op.quantity == 11
    assert op.budget_max_cents == 5_400_000
    assert op.unit_price_cents == 489_400
    assert op.previous_quantity == 20


def test_replacement_uses_inherited_total_budget_when_current_turn_omits_budget():
    cart = [{"sku": "GAM-0006", "name": "Dell G16 Gaming Laptop", "quantity": 20}]
    catalog = lambda _tenant: [{  # noqa: E731
        "sku": "LAP-PROART5070",
        "name": "ASUS ProArt 16 RTX 5070",
        "brand": "ASUS",
        "price_cents": 489400,
        "active": True,
    }]
    envelope = TurnEnvelope.from_suggest_params(
        query=("Replace the Dell G16 with the ASUS ProArt 16 RTX 5070 and use the maximum "
               "quantity the same total can afford."),
        uid="u1",
        tenant_id="t1",
        cart=cart,
        session={"accepted_constraints": {
            "total_budget_cents": 5_400_000,
            "budget_scope": "total",
            "quantity": 20,
        }},
    )
    plan = resolve_cart_mutation(
        envelope,
        llm_fn=_fixed_llm({"ops": [{
            "action": "replace_item",
            "targets": ["Dell G16"],
            "replacement": "ASUS ProArt 16 RTX 5070",
            "quantity_mode": "max_affordable",
        }], "confidence": 0.95}),
        catalog_candidates_fn=catalog,
    )

    assert not plan.ambiguous
    assert plan.ops[0].quantity == 11
    assert plan.ops[0].budget_max_cents == 5_400_000


def test_replacement_fails_closed_when_catalog_name_is_ambiguous():
    cart = [{"sku": "OLD", "name": "Old Workstation", "quantity": 2}]
    catalog = lambda _tenant: [  # noqa: E731
        {"sku": "NEW-A", "name": "Acme Pro", "brand": "Acme", "price_cents": 10000},
        {"sku": "NEW-B", "name": "Acme Pro Plus", "brand": "Acme", "price_cents": 12000},
    ]
    plan = resolve_cart_mutation(
        _env("replace the old workstation with Acme", cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "replace_item", "targets": ["Old Workstation"],
                                     "replacement": "Acme"}], "confidence": 0.9}),
        catalog_candidates_fn=catalog,
    )

    assert not plan.ops
    assert plan.ambiguous == ("Acme",)


def test_conflicting_remove_and_quantity_plan_requires_clarification():
    cart = [{"sku": "GAM-0006", "name": "Dell G16 Gaming Laptop", "quantity": 20}]
    plan = resolve_cart_mutation(
        _env("replace the Dell G16 with a ProArt", cart=cart),
        llm_fn=_fixed_llm({"ops": [
            {"action": "remove_items", "targets": ["Dell G16"]},
            {"action": "set_quantity", "targets": ["Dell G16"], "quantity": 20},
        ], "confidence": 0.9}),
    )

    assert plan.needs_clarification
    assert "conflicting remove and quantity" in plan.ambiguous[0]


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


def test_named_clear_cannot_authorize_clear_all_and_removes_only_named_line():
    """Regression: `clear "Asus TUF..."` must never wipe the whole cart.

    Even if the model proposes clear_all, the platform binds the shopper's named
    target to one real cart line and narrows the consequence to remove_items.
    """
    cart = [
        {"sku": "ASUS-TUF", "name": 'Asus TUF Gaming F16 16" FHD+ 144Hz Gaming Laptop',
         "quantity": 20},
        {"sku": "HP-OMEN", "name": 'HP OMEN MAX 16" RTX 5080 Gaming Laptop',
         "quantity": 20},
    ]
    plan = resolve_cart_mutation(
        _env('clear "Asus TUF Gaming F16 16\\" FHD+ 144Hz Gam" please', cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}], "confidence": 0.96}),
    )

    assert not plan.ambiguous
    assert [(op.action, op.target_skus) for op in plan.ops] == [
        ("remove_items", ("ASUS-TUF",)),
    ]


def test_named_clear_that_does_not_bind_asks_and_never_wipes():
    plan = resolve_cart_mutation(
        _env('clear "the old gaming one" please'),
        llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}], "confidence": 0.96}),
    )

    assert not plan.ops
    assert plan.needs_clarification
    assert "which cart item" in plan.ambiguous[0]


def test_named_clear_recovers_model_omission_only_when_one_real_line_binds():
    cart = [
        {"sku": "ASUS-TUF", "name": 'Asus TUF Gaming F16 16" FHD+ 144Hz Gaming Laptop',
         "quantity": 20},
        {"sku": "HP-OMEN", "name": 'HP OMEN MAX 16" RTX 5080 Gaming Laptop',
         "quantity": 20},
    ]
    plan = resolve_cart_mutation(
        _env('clear "Asus TUF Gaming F16 16\\" FHD+ 144Hz Gam" please', cart=cart),
        llm_fn=_fixed_llm({"ops": [], "confidence": 0.2}),
    )

    assert not plan.ambiguous
    assert [(op.action, op.target_skus) for op in plan.ops] == [
        ("remove_items", ("ASUS-TUF",)),
    ]


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


def test_malformed_replace_with_only_quantity_normalizes_to_set_quantity():
    plan = resolve_cart_mutation(
        _env("actually make the Lenovo IdeaPad 15 instead", cart=[{
            "sku": "LAP-IDEAP3I9",
            "name": 'Lenovo IdeaPad Slim 3i 15.3" 2K Laptop (Intel Core i7)[1TB]',
            "quantity": 25,
        }]),
        llm_fn=_fixed_llm({"ops": [{"action": "replace_item", "targets": ["IdeaPad"],
                                     "replacement": None, "quantity": 15}],
                              "confidence": 0.92}),
    )
    assert not plan.ambiguous
    assert len(plan.ops) == 1
    assert plan.ops[0].action == "set_quantity"
    assert plan.ops[0].quantity == 15


def test_malformed_replace_recovers_trailing_quantity_for_existing_bulk_line():
    plan = resolve_cart_mutation(
        _env("actually make the Lenovo IdeaPad 15 instead", cart=[{
            "sku": "LAP-IDEAP3I9",
            "name": 'Lenovo IdeaPad Slim 3i 15.3" 2K Laptop (Intel Core i7)[1TB]',
            "quantity": 25,
        }]),
        llm_fn=_fixed_llm({"ops": [{"action": "replace_item", "targets": ["IdeaPad"],
                                     "replacement": "Lenovo IdeaPad 15", "quantity": None}],
                              "confidence": 0.95}),
    )
    assert not plan.ambiguous
    assert len(plan.ops) == 1
    assert plan.ops[0].action == "set_quantity"
    assert plan.ops[0].quantity == 15


def test_reducing_an_existing_sourced_line_preserves_sourcing_authorization():
    cart = [{
        "sku": "LAP-IDEAP3I9",
        "name": 'Lenovo IdeaPad Slim 3i 15.3" 2K Laptop',
        "quantity": 25,
        "available_now": 12,
        "sourcing_required": True,
    }]
    plan = resolve_cart_mutation(
        _env("set the IdeaPad to 15", cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"],
                                     "quantity": 15}], "confidence": 0.95}),
    )
    assert plan.ops[0].previous_quantity == 25
    assert plan.ops[0].quantity == 15
    assert plan.ops[0].allow_sourcing is True


def test_relative_quantity_modes_are_recomputed_from_the_current_cart():
    cart = [{
        "sku": "LAP-IDEAP3I9",
        "name": "Lenovo IdeaPad Slim 3i Laptop",
        "quantity": 20,
    }]
    cases = [
        ("add 5 units to the IdeaPad", "add", 5, 25),
        ("take 5 units off the IdeaPad", "subtract", 5, 15),
        ("double the IdeaPad quantity", "multiply", 2, 40),
        ("halve the IdeaPad quantity", "divide", 2, 10),
    ]

    for query, mode, operand, expected in cases:
        plan = resolve_cart_mutation(
            _env(query, cart=cart),
            llm_fn=_fixed_llm({"ops": [{
                "action": "set_quantity",
                "targets": ["IdeaPad"],
                "quantity_mode": mode,
                "quantity": operand,
            }], "confidence": 0.95}),
        )
        assert not plan.ambiguous, query
        assert plan.ops[0].quantity == expected, query


def test_relative_quantity_is_authorized_from_shopper_words_not_model_arithmetic():
    cart = [{
        "sku": "LAP-IDEAP3I9",
        "name": "Lenovo IdeaPad Slim 3i Laptop",
        "quantity": 20,
    }]
    plan = resolve_cart_mutation(
        _env("add 5 units to the IdeaPad", cart=cart),
        llm_fn=_fixed_llm({"ops": [{
            "action": "set_quantity", "targets": ["IdeaPad"], "quantity": 25,
        }], "confidence": 0.95}),
    )

    assert not plan.ambiguous
    assert plan.ops[0].quantity == 25


def test_set_quantity_overflow_dropped_not_clamped():
    # beyond the pure overflow sanity bound the op is dropped — NEVER silently rewritten to a
    # number the shopper didn't say (the old 100k clamp misquoted intent).
    plan = resolve_cart_mutation(
        _env("set the IdeaPad to 999999999"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 999999999}]}))
    assert plan.is_empty


def test_set_quantity_above_line_gate_passes_through():
    # 600 > cart.py._MAX_LINE_QTY (500) but within sanity: the op is KEPT with the shopper's real
    # number — the handler is the ONE authoritative quantity gate and rejects it honestly.
    plan = resolve_cart_mutation(
        _env("set the IdeaPad to 600"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 600}]}))
    assert plan.ops[0].quantity == 600


def test_fractional_quantity_dropped_not_truncated():
    plan = resolve_cart_mutation(
        _env("set the IdeaPad to 2.9"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity", "targets": ["IdeaPad"], "quantity": 2.9}]}))
    assert plan.is_empty      # 2.9 is not a cart quantity; never silently becomes 2


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


def test_product_search_drops_hallucinated_targeted_cart_operation():
    """A populated cart must not turn an ordinary product search into a cart clarification."""
    plan = resolve_cart_mutation(
        _env("a Wacom drawing tablet for high school digital art under $500"),
        llm_fn=_fixed_llm({
            "ops": [{"action": "replace_item", "targets": ["the cart item"],
                     "replacement": "Wacom drawing tablet"}],
            "confidence": 0.9,
        }),
    )

    assert plan.is_empty
    assert not plan.ambiguous


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


# ── C0 hardening: caps + DF scoring (GPT-5.6 review-5 #9/#10) ───────────────────

def test_ops_capped_runaway_model_output():
    plan = resolve_cart_mutation(
        _env("clear my cart"),
        llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}] * 50}))
    assert len(plan.ops) <= 8      # 50-op response truncated, never iterated in full


def test_targets_capped_per_op():
    targets = [f"item {i}" for i in range(30)]
    plan = resolve_cart_mutation(
        _env("remove a bunch of things"),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": targets}]}))
    # nothing binds (no such items) — but only the first 12 were even considered
    assert len(plan.ambiguous) <= 12


def test_prompt_lines_capped():
    from src.app.services.recommendation_core.cart_resolver import _build_prompt
    big_cart = [{"sku": f"S-{i}", "name": f"Product {i}", "quantity": 1} for i in range(45)]
    prompt = _build_prompt(_env("clear it", cart=big_cart),
                           [{"sku": f"S-{i}", "name": f"Product {i}", "quantity": 1} for i in range(45)])
    assert "and 5 more lines" in prompt
    assert "[39]" in prompt and "[40]" not in prompt


def test_df_single_line_cart_generic_name_binds():
    # DF scoring (replaces the electronics stoplist): with ONE laptop in the cart, 'the laptop'
    # is unambiguous — a single-line cart keeps all its tokens as identifiers.
    cart = [{"sku": "LAP-ONLY", "name": "Lenovo IdeaPad Slim 3i Laptop", "quantity": 1}]
    plan = resolve_cart_mutation(
        _env("remove the laptop", cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the laptop"]}]}))
    assert plan.ops and plan.ops[0].target_skus == ("LAP-ONLY",)


def test_df_shared_token_is_not_distinctive_any_vertical():
    # vertical-blind proof: works for a pharmacy cart with zero electronics vocabulary —
    # 'tablets' appears in both lines (df=2) so it cannot bind; 'ibuprofen' (df=1) can.
    cart = [{"sku": "MED-1", "name": "Ibuprofen 200mg Tablets", "quantity": 1},
            {"sku": "MED-2", "name": "Paracetamol 500mg Tablets", "quantity": 1}]
    ambiguous = resolve_cart_mutation(
        _env("remove the tablets", cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the tablets"]}]}))
    assert ambiguous.ops == () and "the tablets" in ambiguous.ambiguous
    bound = resolve_cart_mutation(
        _env("remove the ibuprofen", cart=cart),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the ibuprofen"]}]}))
    assert bound.ops and bound.ops[0].target_skus == ("MED-1",)


# ── SHOPPER-ambiguity gate (the 'add 5 more Lenovo' with two Lenovo lines bug) ──────────────────

def test_ambiguous_brand_reference_asks_not_guesses():
    # the model resolves the under-specified 'Lenovo' to the FIRST Lenovo line; the platform must
    # still ASK, because the shopper's own word matches TWO Lenovo lines — never guess whose qty.
    plan = resolve_cart_mutation(
        _env("add 5 more Lenovo"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity",
                                    "targets": ["Lenovo ThinkPad L13 Gen 6"], "quantity": 35}],
                           "confidence": 0.95}))
    assert not plan.ops                         # did NOT guess a product to mutate
    assert plan.ambiguous                       # asked instead
    assert "ThinkPad" in plan.ambiguous[0] and "IdeaPad" in plan.ambiguous[0]   # both candidates listed


def test_full_name_disambiguates_and_binds():
    # a DISTINCTIVE token ('IdeaPad') in the shopper's own words singles out the line → bind, no ask.
    plan = resolve_cart_mutation(
        _env("set the Lenovo IdeaPad to 20"),
        llm_fn=_fixed_llm({"ops": [{"action": "set_quantity",
                                    "targets": ["Lenovo IdeaPad Slim 3i"], "quantity": 20}],
                           "confidence": 0.95}))
    assert not plan.ambiguous
    assert [(o.action, o.target_skus, o.quantity) for o in plan.ops] == [
        ("set_quantity", ("LAP-IDEAP3I9",), 20)]


def test_uniquely_matching_brand_binds():
    # 'HP' matches exactly one line → distinctive → bind (the gate only fires on MULTI-line matches).
    plan = resolve_cart_mutation(
        _env("remove the HP"),
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items",
                                    "targets": ["HP Envy x360"]}], "confidence": 0.9}))
    assert not plan.ambiguous
    assert [(o.action, o.target_skus) for o in plan.ops] == [("remove_items", ("LAP-HPENVY01",))]


# ── Track C: whole-cart op authorization by the shopper's OWN words ─────────────────────────────

def test_clear_all_requires_shopper_clear_intent():
    # model hallucinates clear_all but the shopper never asked to clear → do NOT wipe; ASK.
    plan = resolve_cart_mutation(
        _env("what's the cheapest laptop?"),
        llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}], "confidence": 0.9}))
    assert not plan.ops and plan.ambiguous          # surfaced for confirmation, not executed
    # a real clear intent → executed
    plan2 = resolve_cart_mutation(
        _env("clear my cart"),
        llm_fn=_fixed_llm({"ops": [{"action": "clear_all"}], "confidence": 0.9}))
    assert [o.action for o in plan2.ops] == ["clear_all"] and not plan2.ambiguous


def test_keep_only_without_keep_intent_is_rejected_catches_misclassification():
    # the case-B misread: 'make the Lenovo 15' → model returns keep_only, dropping the number. No
    # keep-intent word → reject the destructive keep_only and ASK (never silently wipe the rest).
    plan = resolve_cart_mutation(
        _env("make the Lenovo IdeaPad 15"),
        llm_fn=_fixed_llm({"ops": [{"action": "keep_only", "targets": ["Lenovo IdeaPad Slim 3i"]}],
                           "confidence": 0.9}))
    assert not plan.ops and plan.ambiguous
    # a genuine keep-only → executed
    plan2 = resolve_cart_mutation(
        _env("keep only the IdeaPad"),
        llm_fn=_fixed_llm({"ops": [{"action": "keep_only", "targets": ["Lenovo IdeaPad Slim 3i"]}],
                           "confidence": 0.9}))
    assert [(o.action, o.target_skus) for o in plan2.ops] == [("keep_only", ("LAP-IDEAP3I9",))]
