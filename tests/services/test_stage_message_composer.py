"""V2 review-10 P0.5 — the explicit-priority message composer.

Replaces the old execution-order-wins mutation (whichever stage ran LAST set resp.message) with
CoreResponse.set_message(text, priority): a stage declares WHERE its prose sits in the hierarchy,
so inserting or reordering a stage can never silently steal the buyer's sentence. These tests pin
the priority ladder + the never-blank-claim guarantee so a future edit can't regress them.
"""
from src.app.services.recommendation_core.envelope import (
    CoreResponse,
    MsgPriority,
    StageResult,
    TurnEnvelope,
)


def _resp() -> CoreResponse:
    return CoreResponse(envelope=TurnEnvelope.from_suggest_params(query="x", uid="u"))


def test_lane_message_outranks_within_budget_confirm():
    # reproduces the old `if not resp.message` guard: a lane-base message (closest-match/compare)
    # must survive the fill-only within-budget confirm.
    r = _resp()
    r.set_message("closest-match from lane", MsgPriority.LANE_BASE)
    r.set_message("within your budget confirm", MsgPriority.CAPABILITY_WITHIN_BUDGET)
    assert r.message == "closest-match from lane"


def test_within_budget_confirm_fills_empty_slot():
    r = _resp()
    assert r.set_message("within your budget confirm", MsgPriority.CAPABILITY_WITHIN_BUDGET)
    assert r.message == "within your budget confirm"


def test_capability_statement_overrides_lane_base():
    r = _resp()
    r.set_message("closest-match from lane", MsgPriority.LANE_BASE)
    r.set_message("nothing at $900 fully meets gaming", MsgPriority.CAPABILITY_STATEMENT)
    assert r.message == "nothing at $900 fully meets gaming"


def test_bulk_verdict_overrides_capability_statement():
    # the procurement/bulk case: bulk economics must win over the capability tradeoff, exactly as
    # the old code (bulk stage ran last). Now it's explicit, not positional.
    r = _resp()
    r.set_message("capability tradeoff", MsgPriority.CAPABILITY_STATEMENT)
    r.set_message("20 units ~ $17,980, over your $16,000", MsgPriority.BULK_VERDICT)
    assert r.message.startswith("20 units")


def test_scope_clarify_is_top_non_refusal():
    r = _resp()
    r.set_message("bulk verdict", MsgPriority.BULK_VERDICT)
    r.set_message("is $1400 per laptop or the total?", MsgPriority.BULK_SCOPE_CLARIFY)
    assert r.message.startswith("is $1400")


def test_blank_text_never_claims_the_slot():
    # the safety upgrade over the old mutation: resp.message = "" used to be able to WIPE a good
    # message. A blank (even at a higher priority) must not claim the slot.
    r = _resp()
    r.set_message("real message", MsgPriority.LANE_BASE)
    assert r.set_message("   ", MsgPriority.BULK_VERDICT) is False
    assert r.message == "real message"


def test_priority_ladder_is_monotonic():
    # a self-check that the constants keep their intended order (a reorder here would break the
    # behaviour the tests above assert).
    assert (MsgPriority.CAPABILITY_WITHIN_BUDGET < MsgPriority.LANE_BASE
            < MsgPriority.CAPABILITY_STATEMENT < MsgPriority.BULK_VERDICT
            < MsgPriority.BULK_SCOPE_CLARIFY < MsgPriority.REFUSAL)


def test_finalize_surfaces_stage_telemetry():
    r = _resp()
    r.record_stage("capability_budget", latency_ms=12.3, won_message=True)
    r.record_stage("shelf", latency_ms=4.5)
    r.finalize()
    sr = r.extras.get("stage_results")
    assert sr and sr[0]["stage"] == "capability_budget" and sr[0]["won_message"] is True
    assert sr[1]["stage"] == "shelf" and sr[1]["won_message"] is False


def test_finalize_recovery_still_fires_when_no_stage_claimed():
    # composer + recovery coexist: nothing claimed → the never-empty floor still guarantees prose.
    r = _resp()
    r.finalize()
    assert str(r.message or "").strip()


def test_stage_result_as_dict_omits_empty_data():
    assert "data" not in StageResult(stage="s").as_dict()
    assert StageResult(stage="s", data={"k": 1}).as_dict()["data"] == {"k": 1}
