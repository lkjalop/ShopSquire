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
