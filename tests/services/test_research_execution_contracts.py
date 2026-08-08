from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.app.services.recommendation_core.research_contracts import (
    AmbiguityHypothesis,
    AmbiguityObject,
    ProviderExecutionReceipt,
    ResearchTurnContract,
    ResolutionOwner,
    SpanningQueryContract,
    SpanningResearchQuery,
    TurnObligation,
)


def _obligation(
    obligation_id: str,
    obligation_type: str,
    primary: ResolutionOwner,
    *owners: ResolutionOwner,
    ambiguity_ids: list[str] | None = None,
) -> TurnObligation:
    return TurnObligation(
        obligation_id=obligation_id,
        obligation_type=obligation_type,
        description=f"Resolve {obligation_type}",
        primary_owner=primary,
        resolution_owners=[primary, *owners],
        ambiguity_ids=ambiguity_ids or [],
    )


def test_one_turn_carries_multiple_independently_owned_obligations():
    ambiguity = AmbiguityObject(
        ambiguity_id="workload-meaning",
        ambiguity_type="unfamiliar combined workload",
        subject_span="PLC-controlled factory and cyberattacks against the OT network",
        description="The requested topology and simulator scale are not yet established",
        hypotheses=[
            AmbiguityHypothesis(
                hypothesis_id="vm-range",
                label="VM and network-appliance OT cyber range",
            ),
            AmbiguityHypothesis(
                hypothesis_id="plc-sim",
                label="OT cyber range with a PLC-controlled plant simulator",
            ),
        ],
        shared_requirement_candidates=["virtualisation", "NVMe storage"],
        divergent_axes=["simultaneous node count", "simulator compatibility"],
        resolution_owners=[ResolutionOwner.RESEARCH, ResolutionOwner.BUYER],
    )
    contract = ResearchTurnContract(
        turn_id="turn-1",
        ambiguities=[ambiguity],
        obligations=[
            _obligation(
                "workload", "workload ambiguity", ResolutionOwner.RESEARCH,
                ResolutionOwner.BUYER, ambiguity_ids=["workload-meaning"],
            ),
            _obligation("budget", "budget arithmetic", ResolutionOwner.COMPUTATION),
            _obligation("delivery", "delivery shortfall", ResolutionOwner.SUPPLIER),
            _obligation("capability", "exact product capability", ResolutionOwner.CATALOG),
        ],
    )

    assert [item.primary_owner for item in contract.obligations] == [
        ResolutionOwner.RESEARCH,
        ResolutionOwner.COMPUTATION,
        ResolutionOwner.SUPPLIER,
        ResolutionOwner.CATALOG,
    ]
    assert contract.obligations[0].resolution_owners == [
        ResolutionOwner.RESEARCH,
        ResolutionOwner.BUYER,
    ]


def test_ambiguity_type_is_open_vocabulary_but_hypotheses_are_bounded():
    item = AmbiguityObject(
        ambiguity_id="novel-science",
        ambiguity_type="buyer-invented quantum-biological workflow uncertainty",
        subject_span="simulate a new drug",
        description="Unknown workload and product-category boundary",
        hypotheses=[AmbiguityHypothesis(hypothesis_id="h1", label="Local computation")],
        resolution_owners=[ResolutionOwner.RESEARCH, ResolutionOwner.HUMAN],
    )
    assert item.ambiguity_type.startswith("buyer-invented")

    with pytest.raises(ValidationError, match="at most 3 items"):
        AmbiguityObject(
            ambiguity_id="too-many",
            ambiguity_type="unknown",
            subject_span="unknown request",
            description="Unbounded interpretations",
            hypotheses=[
                AmbiguityHypothesis(hypothesis_id=f"h{i}", label=f"Hypothesis {i}")
                for i in range(4)
            ],
            resolution_owners=[ResolutionOwner.RESEARCH],
        )


def test_spanning_query_contract_covers_axes_with_bounded_fanout():
    queries = [
        SpanningResearchQuery(
            query_id="q-concept",
            obligation_ids=["workload"],
            purpose="concept",
            subject_span="OT cyber range",
            query_text="official OT cyber range PLC simulation",
            coverage_axes=["concept"],
            allowed_claim_types=["concept_identity"],
            max_results=4,
        ),
        SpanningResearchQuery(
            query_id="q-compat",
            obligation_ids=["workload", "capability"],
            purpose="compatibility",
            subject_span="PLC-controlled factory",
            query_text="official PLC simulator supported drivers requirements",
            coverage_axes=["requirements", "compatibility"],
            allowed_claim_types=["minimum_requirements", "compatibility"],
            max_results=4,
        ),
    ]
    plan = SpanningQueryContract(
        contract_id="research-1",
        required_coverage_axes=["concept", "requirements", "compatibility"],
        queries=queries,
        max_queries=2,
        max_total_results=8,
    )
    assert len(plan.queries) == 2
    assert sum(item.max_results for item in plan.queries) == 8


def test_spanning_query_contract_rejects_missing_axis_and_excess_fanout():
    query = SpanningResearchQuery(
        query_id="q1",
        obligation_ids=["workload"],
        purpose="concept",
        subject_span="digital twin",
        query_text="official digital twin definition",
        coverage_axes=["concept"],
        max_results=5,
    )
    with pytest.raises(ValidationError, match="not spanned"):
        SpanningQueryContract(
            contract_id="missing-axis",
            required_coverage_axes=["concept", "compatibility"],
            queries=[query],
        )
    with pytest.raises(ValidationError, match="exceeds max_queries"):
        SpanningQueryContract(
            contract_id="too-wide",
            required_coverage_axes=["concept"],
            queries=[query, query.model_copy(update={"query_id": "q2"})],
            max_queries=1,
        )


def test_live_discovery_receipt_proves_real_network_execution():
    started = datetime.now(timezone.utc)
    receipt = ProviderExecutionReceipt(
        receipt_id="receipt:live:1",
        execution_id="certification-run-1",
        provider_capability="WEB_DISCOVERY",
        provider_id="local_searxng",
        certification_run_id="certification-run-1",
        provider_endpoint_host="127.0.0.1",
        query_id="q1",
        query_hash="abcdef1234567890",
        query_purpose="workload",
        obligation_ids=["workload"],
        execution_status="completed",
        fixture=False,
        network_execution=True,
        external_call_dispatched=True,
        cache_status="miss",
        billing_class="free",
        started_at=started,
        completed_at=started + timedelta(milliseconds=30),
        http_status=200,
        result_count=5,
        allowlisted_result_count=3,
        response_body_hash="12345678abcdef",
    )
    assert receipt.trace_execution_state == "completed"
    assert receipt.network_execution is True
    assert receipt.billing_class == "free"
    assert receipt.as_trace_dict()["execution"] == "completed"


def test_fixture_and_cache_receipts_do_not_claim_network_or_paid_calls():
    started = datetime.now(timezone.utc)
    fixture = ProviderExecutionReceipt(
        receipt_id="receipt:fixture:1",
        execution_id="deterministic-1",
        provider_capability="WEB_DISCOVERY",
        provider_id="searxng_fixture",
        execution_status="completed",
        fixture=True,
        network_execution=False,
        external_call_dispatched=False,
        cache_status="not_checked",
        billing_class="not_applicable",
        started_at=started,
        completed_at=started,
        result_count=4,
        allowlisted_result_count=4,
    )
    cached = ProviderExecutionReceipt(
        receipt_id="receipt:cache:1",
        execution_id="certification-2",
        provider_capability="OFFICIAL_ORIGIN_FETCH",
        provider_id="governed_origin_fetch",
        execution_status="completed",
        fixture=False,
        network_execution=False,
        external_call_dispatched=False,
        cache_status="fresh_hit",
        billing_class="not_applicable",
        started_at=started,
        completed_at=started,
        result_count=1,
        allowlisted_result_count=1,
    )
    assert fixture.trace_execution_state == "completed"
    assert cached.trace_execution_state == "completed"
    assert not fixture.external_call_dispatched and not cached.external_call_dispatched


def test_live_certification_receipt_requires_independent_network_observations():
    started = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="live certification receipt requires"):
        ProviderExecutionReceipt(
            receipt_id="receipt:incomplete-live",
            execution_id="certification-run-2",
            certification_run_id="certification-run-2",
            provider_capability="WEB_DISCOVERY",
            provider_id="local_searxng",
            execution_status="completed",
            fixture=False,
            network_execution=True,
            external_call_dispatched=True,
            cache_status="miss",
            billing_class="free",
            started_at=started,
            completed_at=started,
        )


@pytest.mark.parametrize("status", ["planned", "rejected_admission", "not_dispatched"])
def test_rejected_or_unexecuted_receipt_cannot_masquerade_as_execution(status):
    kwargs = {
        "receipt_id": f"receipt:{status}",
        "execution_id": "run-1",
        "provider_capability": "WEB_DISCOVERY",
        "provider_id": "local_searxng",
        "execution_status": status,
        "fixture": False,
        "network_execution": True,
        "external_call_dispatched": True,
        "cache_status": "miss",
        "billing_class": "free",
    }
    if status == "rejected_admission":
        kwargs["rejection_reason"] = "internal_effort_allowance_exceeded"
    with pytest.raises(ValidationError, match="cannot claim dispatch"):
        ProviderExecutionReceipt(**kwargs)


def test_rejected_receipt_projects_rejected_not_pending_or_completed():
    receipt = ProviderExecutionReceipt(
        receipt_id="receipt:rejected",
        execution_id="run-1",
        provider_capability="WEB_DISCOVERY",
        provider_id="local_searxng",
        execution_status="rejected_admission",
        fixture=False,
        network_execution=False,
        external_call_dispatched=False,
        cache_status="not_checked",
        billing_class="not_applicable",
        rejection_reason="internal_effort_allowance_exceeded",
    )
    assert receipt.trace_execution_state == "rejected"
    assert receipt.trace_execution_state not in {"pending", "completed"}
    assert receipt.as_trace_dict()["execution"] == "rejected"
    assert receipt.as_trace_dict()["network_execution"] is False


def test_research_turn_rejects_dangling_ambiguity_and_obligation_references():
    obligation = _obligation(
        "workload", "workload", ResolutionOwner.RESEARCH,
        ambiguity_ids=["does-not-exist"],
    )
    with pytest.raises(ValidationError, match="unknown ambiguity references"):
        ResearchTurnContract(turn_id="turn", obligations=[obligation])

    query_contract = SpanningQueryContract(
        contract_id="research",
        required_coverage_axes=["concept"],
        queries=[SpanningResearchQuery(
            query_id="q1",
            obligation_ids=["not-an-obligation"],
            purpose="concept",
            subject_span="new workload",
            query_text="official new workload requirements",
            coverage_axes=["concept"],
        )],
    )
    with pytest.raises(ValidationError, match="unknown obligation references"):
        ResearchTurnContract(
            turn_id="turn",
            obligations=[_obligation("workload", "workload", ResolutionOwner.RESEARCH)],
            query_contract=query_contract,
        )
