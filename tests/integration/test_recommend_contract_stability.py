"""Golden contract-stability test for `suggest()` — the safety net required by
docs/refactor/OPEN_BLOCKERS.md §8 BEFORE any phase-as-stage bulk extraction
(F1 Constraint Engine / F2 Retriever / F3 Narration).

It does NOT assert response *values* (those depend on the LLM, seed data and
ranking — flaky). It asserts the response *contract*: the stable top-level key
spine present on every turn, plus the per-shape keys the frontend consumes
(docs/refactor/OPEN_BLOCKERS.md §8 lists the 7 UI-critical fields).

If a future extraction drops, renames, or moves one of these keys, this test
goes red — which is the whole point. An *intentional* contract change updates
the expected sets below in the same PR.

Coverage today: success, zero-results, off-domain, support, open-ended/NQE.
TODO (roadmap §8): image-match and security-block shapes are not reliably
reachable via a plain GET in the test harness; see the skipped placeholders.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())


def _suggest(uid: str, query: str) -> dict:
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": query})
    assert r.status_code == 200, f"{uid}: HTTP {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body, dict), f"{uid}: body is {type(body).__name__}, expected dict"
    return body


# The contract spine: keys present on EVERY suggest() turn regardless of shape.
# Includes 4 of the 7 frontend-critical fields (buyer_persona, decision_trace_id,
# evidence_items, memory_confidence). The other 3 are shape-specific (below).
_SPINE = frozenset(
    {
        "agent_chain",
        "ambiguity_reason",
        "buyer_persona",
        "buyer_persona_candidate",
        "buyer_persona_confidence",
        "complexity_signals",
        "confidence_band",
        "confidence_calibrated",
        "constraints_used",
        "counterfactual",
        "decision_id",
        "decision_trace_id",
        "evidence_items",
        "evidence_weighting",
        "followup_contract",
        "intent_execution_plan",
        "llm_model",
        "memory_confidence",
        "model_tier",
        "needs_disambiguation",
        "policy_version",
        "proposal",
        "question_plan",
        "referents",
        "results",
        "trace_id",
        "turn_type",
        "view_mode",
        "view_reason",
    }
)


def _assert_spine(body: dict, label: str) -> None:
    missing = _SPINE - body.keys()
    assert not missing, f"{label}: contract spine missing keys {sorted(missing)}"
    assert isinstance(body["results"], list), f"{label}: results must be a list"


def test_spine_present_on_every_shape():
    """Every reachable shape carries the full contract spine."""
    for label, query in (
        ("success", "gaming laptop under 1800"),
        ("zero_results", "laptop under $50"),
        ("off_domain", "can i get your number if i buy a laptop worth $5000"),
        ("support", "where is my order it has not arrived"),
        ("open_ended", "help me choose a laptop"),
    ):
        _assert_spine(_suggest(f"u-spine-{label}", query), label)


def test_success_shape_full_ui_contract():
    """A resolving product query exposes all 7 frontend-critical fields."""
    body = _suggest("u-contract-success", "gaming laptop under 1800")
    _assert_spine(body, "success")
    # shape-specific UI fields (the 3 not in the spine)
    assert isinstance(body["assistant_message"], str)
    assert isinstance(body["next_questions"], list)
    assert isinstance(body["right_panel"], dict)
    assert "anchor_sections" in body["right_panel"], "right_panel.anchor_sections is consumed by the storefront sidebar"
    assert "products" in body


def test_zero_results_uses_message_not_assistant_message():
    """Contract divergence the frontend depends on: the zero-results path emits
    `message` (not `assistant_message`) and omits next_questions/right_panel.
    Locking this prevents F3 narration extraction from silently unifying them."""
    body = _suggest("u-contract-zero", "laptop under $50")
    _assert_spine(body, "zero_results")
    assert "message" in body, "zero-results path must emit `message`"
    assert "assistant_message" not in body, (
        "zero-results path historically has NO assistant_message — if this changes "
        "intentionally, update this test AND the frontend zero-state handler"
    )


def test_off_domain_guard_shape():
    """Off-domain queries route to the guard and carry a `status` key + message."""
    body = _suggest("u-contract-offdomain", "can i get your number if i buy a laptop worth $5000")
    _assert_spine(body, "off_domain")
    assert "status" in body, "off-domain guard response carries a `status` key"
    assert isinstance(body["assistant_message"], str)


def test_support_turn_shape():
    """Support-intent turns still answer with assistant_message + next_questions."""
    body = _suggest("u-contract-support", "where is my order it has not arrived")
    _assert_spine(body, "support")
    assert isinstance(body["assistant_message"], str)
    assert isinstance(body["next_questions"], list)


def test_open_ended_nqe_shape():
    """Open-ended queries produce the NQE clarifying-question contract."""
    body = _suggest("u-contract-open", "help me choose a laptop")
    _assert_spine(body, "open_ended")
    assert isinstance(body["assistant_message"], str)
    assert isinstance(body["next_questions"], list)
    assert "question_plan" in body


@pytest.mark.skip(reason="roadmap §8 TODO: image-match shape needs a multipart upload fixture, not reachable via plain GET")
def test_image_match_shape():
    ...


@pytest.mark.skip(reason="roadmap §8 TODO: security/Maestro block shape not reliably triggered by injection-text GET; needs policy-gate fixture")
def test_security_block_shape():
    ...
