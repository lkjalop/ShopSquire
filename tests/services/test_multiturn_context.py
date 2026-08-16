"""Multi-turn context threading — the PRIOR subject is shown to the classifier so a subject-
dropping follow-up ('only 6 people, $19000') stays in-category instead of mis-routing on a stray
word ('drawing class' → Art & Crafts). Model-judged; the deterministic clamps are unchanged."""
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import _build_prompt, _prior_context_block


def _env(q):
    return TurnEnvelope.from_suggest_params(query=q, uid="u", tenant_id="default")


def test_prior_block_present_when_session_has_subject():
    blk = _prior_context_block({"node_path": "Electronics > Computers > Laptops",
                                "use_cases": ["drawing"], "budget_max_cents": 1_600_000})
    assert "PRIOR TURN" in blk and "Laptops" in blk and "drawing" in blk and "$16,000" in blk


def test_no_prior_block_without_subject():
    assert _prior_context_block(None) == ""
    assert _prior_context_block({"use_cases": ["drawing"]}) == ""   # no node_path → no block


def test_prompt_includes_prior_when_given_omits_when_not():
    prior = {"node_path": "Electronics > Computers > Laptops", "use_cases": ["drawing"],
             "budget_max_cents": None}
    with_prior = _build_prompt(_env("only 6 people, $19000"), [], [], ["drawing"], prior=prior)
    assert "PRIOR TURN" in with_prior and "Laptops" in with_prior
    without = _build_prompt(_env("a laptop for drawing"), [], [], ["drawing"])
    assert "PRIOR TURN" not in without      # first turn / no session → stateless, unchanged


def test_prompt_carries_active_procurement_lane_without_forcing_policy_questions():
    prior = {"node_path": "Electronics > Computers > Laptops", "use_cases": ["office"],
             "budget_max_cents": 5_000_000, "lane": "PROCUREMENT"}
    prompt = _build_prompt(_env("what is the delivery and sourcing tradeoff?"), [], [], [],
                           prior=prior)
    assert "active_lane=PROCUREMENT" in prompt
    assert "current order's quantity, sourcing, delivery" in prompt
    assert "general policy questions remain POLICY_QUESTION" in prompt
    assert "procurement_context=current_order" in prompt


def test_prompt_can_carry_legacy_procurement_lane_without_taxonomy_subject():
    prompt = _build_prompt(_env("what is the delivery and sourcing tradeoff?"), [], [], [],
                           prior={"node_path": None, "use_cases": [],
                                  "budget_max_cents": None, "lane": "PROCUREMENT"})
    assert "category=current product/order" in prompt
    assert "active_lane=PROCUREMENT" in prompt


def test_prompt_contains_server_loaded_case_before_model_interpretation():
    prompt = _build_prompt(
        _env("move 5 of those from Perth to Sydney"), [], [], [],
        prior={
            "node_path": None,
            "use_cases": [],
            "budget_max_cents": None,
            "lane": "PROCUREMENT",
            "procurement_case_state": {
                "case_id": "case-60",
                "revision": 3,
                "objective": "Unreal Engine fleet",
                "workloads": ["Unreal Engine", "Nanite"],
                "requested_quantity": 60,
                "destinations": [
                    {"location_ref": "Sydney", "quantity": 40},
                    {"location_ref": "Perth", "quantity": 20},
                ],
                "temporal": {"required_by": "2026-08-20T17:00:00+10:00"},
            },
        },
    )

    assert "CURRENT CANONICAL PROCUREMENT CASE" in prompt
    assert "case_id=case-60" in prompt
    assert "total_quantity=60" in prompt
    assert "Sydney=40" in prompt and "Perth=20" in prompt
    assert "workloads=Unreal Engine, Nanite" in prompt
    assert "case's own quantity, destinations, delivery approach" in prompt
    assert "never for the active case's fulfilment decision" in prompt
