from dataclasses import dataclass

from src.app.services.image_fallback_advice import image_fallback
from src.app.services.inventory_read_advice import inventory_summary
from src.app.services.policy_answer_service import policy_answer
from src.app.services.support_handoff_advice import prepare_support_handoff


@dataclass
class _Product:
    sku: str
    title: str
    stock: int | None


def test_unknown_policy_is_honest_and_non_consequential():
    result = policy_answer("What is the policy for loyalty point expiration?", tenant_id="tenant-a")
    assert result["answered"] is False
    assert result["action_executed"] is False
    assert "won't invent" in result["message"]


def test_support_advice_never_claims_case_was_filed():
    result = prepare_support_handoff("my laptop arrived damaged", tenant_id="tenant-a")
    assert result["case_id"] is None
    assert result["claim_status"] == "pending_handoff"
    assert result["action_executed"] is False
    assert "nothing is filed" in result["message"]


def test_inventory_advice_reports_unknown_and_zero_distinctly():
    result = inventory_summary([
        _Product("A", "Alpha", None), _Product("B", "Beta", 0), _Product("C", "Gamma", 4),
    ], tenant_id="tenant-a")
    assert "not currently verified" in result["message"]
    assert "currently out of stock" in result["message"]
    assert "4 available" in result["message"]
    assert result["action_executed"] is False


def test_image_fallback_never_builds_second_slate():
    result = image_fallback(analysis_state="degraded", reason="provider_timeout")
    assert result["status"] == "degraded"
    assert result["products"] == []
    assert result["canonical_slate"] is True
