from types import SimpleNamespace

import pytest

from src.app.services.case_publisher_candidate_workflow import (
    execute_case_candidate_research,
)


class _Db:
    def add(self, _row):
        raise AssertionError("zero-yield research must not create a requirement proposal")

    def flush(self):
        pass

    def commit(self):
        pass


@pytest.mark.asyncio
async def test_zero_parser_yield_remains_unresolved_and_creates_no_proposal(monkeypatch):
    candidate = SimpleNamespace(
        candidate_id="pubcand-zero", tenant_id="default", case_id="sc-zero",
        uid="buyer", url="https://publisher.example/landing",
        domain="publisher.example", title="Publisher landing", status="discovered",
        authority_status="not_accepted", approval_scope=None,
        allowed_claim_types_json=[], approved_by=None,
        approval_idempotency_key=None, research_result_json=None,
        requirement_proposal_id=None, version=1, updated_at=None,
    )
    case = SimpleNamespace(case_id="sc-zero", retained_purpose="unfamiliar analysis")
    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        lambda *args, **kwargs: {
            "claims": [], "context_claims": [],
            "unresolved": [{"reason": "no_recognized_scoped_claims"}],
            "source_execution": [{
                "origin_selection_mode": "canonical_direct",
                "publisher_origin_verification": {
                    "status": "unresolved",
                    "ownership_authority": "not_independently_verified",
                },
            }],
            "receipts": [],
            "provider_accounting": {
                "external_calls": 1, "official_origin_fetches": 1,
                "discovery_calls": 0, "paid_calls": 0,
            },
            "evidence_outcome": "unresolved",
        },
    )

    result, error = await execute_case_candidate_research(
        _Db(), candidate=candidate, case=case, tenant_id="default", uid="buyer",
        expected_version=1, idempotency_key="zero-yield-1",
        allowed_claim_types=["minimum_requirements"],
    )

    assert error is None
    assert result is not None
    assert result["research_status"] == "zero_parser_yield"
    assert result["evidence_outcome"] == "unresolved"
    assert result["buyer_requirement_proposal"] is None
    assert result["qualification_authority"] == "none"
    assert result["cart_mutation"] == "not_authorized"
