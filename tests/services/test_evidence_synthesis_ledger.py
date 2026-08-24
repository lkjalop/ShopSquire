from src.app.services.evidence_synthesis_ledger import build_evidence_synthesis_ledger


def _source(source_id: str, domain: str) -> dict:
    return {
        "source_id": source_id,
        "source_class": "official",
        "publisher": source_id.replace("-", " ").title(),
        "review_status": "approved",
        "allowed_domains": [domain],
        "canonical_entrypoints": [f"https://{domain}/requirements"],
        "freshness_sla_hours": 24,
        "publisher_policy": {"direct_origin_required": True},
    }


def test_ledger_preserves_contradiction_failed_source_and_gap() -> None:
    sources = [
        _source("publisher-a", "a.example"),
        _source("publisher-b", "b.example"),
        _source("publisher-c", "c.example"),
    ]
    research = {
        "run_id": "research-held-out",
        "execution_mode": "live_network",
        "hypothesis_ids": ["workload-one"],
        "provider_accounting": {"external_calls": 3, "paid_calls": 0},
        "source_execution": [
            {
                "source_id": source["source_id"],
                "publisher": source["publisher"],
                "selected_origin_url": source["canonical_entrypoints"][0],
                "origin_selection_mode": "canonical_direct",
                "freshness_sla_hours": 24,
                "deadline_status": "within_deadline",
            }
            for source in sources
        ],
        "receipts": [
            {
                "query_id": "publisher-a", "execution_status": "completed",
                "external_call_dispatched": True,
                "started_at": "2026-08-24T00:00:01+00:00",
                "completed_at": "2026-08-24T00:00:02+00:00",
                "origin_observed_at": "2026-08-24T00:00:02+00:00",
                "selected_origin_urls": ["https://a.example/requirements"],
                "query_hash": "a" * 64, "response_body_hash": "1" * 64,
                "billing_class": "free",
            },
            {
                "query_id": "publisher-b", "execution_status": "completed",
                "external_call_dispatched": True,
                "started_at": "2026-08-24T00:00:01+00:00",
                "completed_at": "2026-08-24T00:00:02+00:00",
                "origin_observed_at": "2026-08-24T00:00:02+00:00",
                "selected_origin_urls": ["https://b.example/requirements"],
                "query_hash": "b" * 64, "response_body_hash": "2" * 64,
                "billing_class": "free",
            },
            {
                "query_id": "publisher-c", "execution_status": "failed",
                "external_call_dispatched": True,
                "started_at": "2026-08-24T00:00:01+00:00",
                "completed_at": "2026-08-24T00:00:03+00:00",
                "selected_origin_urls": ["https://c.example/requirements"],
                "query_hash": "c" * 64, "response_body_hash": None,
                "billing_class": "free", "rejection_reason": "source_timeout",
            },
        ],
        "claims": [
            {
                "claim_id": "claim-a", "claim_type": "minimum_requirements",
                "attribute": "memory_gb", "operator": ">=", "value": 16,
                "unit": "GB", "source_id": "publisher-a", "freshness_status": "fresh",
            },
            {
                "claim_id": "claim-b", "claim_type": "minimum_requirements",
                "attribute": "memory_gb", "operator": ">=", "value": 32,
                "unit": "GB", "source_id": "publisher-b", "freshness_status": "fresh",
            },
        ],
        "unresolved": [{"source_id": "publisher-c", "reason": "source_timeout"}],
    }

    ledger = build_evidence_synthesis_ledger(
        case_id="case-1",
        case_revision=4,
        query="official requirements for workload one",
        purpose="workload one",
        consent_receipt={
            "authorized": True,
            "recorded_at": "2026-08-24T00:00:00+00:00",
            "event": "buyer_authorized",
        },
        research=research,
        approved_sources=sources,
        candidate_configuration_ids=["cfg-1"],
    )

    assert ledger.claim_coverage == {
        "accepted": 0, "rejected": 0, "contradicted": 2, "unresolved": 1,
    }
    assert ledger.contradictions[0]["attribute_key"] == "memory_gb"
    assert next(row for row in ledger.sources if row.source_id == "publisher-c").failure_reason == "source_timeout"
    assert ledger.decision_trace_projection["decision_status"] == "provisional_only"
    assert ledger.decision_trace_projection["commerce_authority"] == "none"
    assert ledger.evidence_intent.product_configuration_binding["candidate_configuration_ids"] == ["cfg-1"]


def test_ledger_rejects_missing_consent_before_research_projection() -> None:
    try:
        build_evidence_synthesis_ledger(
            case_id="case-1", case_revision=1, query="q", purpose="p",
            consent_receipt={"authorized": False}, research={},
            approved_sources=[], candidate_configuration_ids=[],
        )
    except ValueError as exc:
        assert str(exc) == "research_consent_receipt_required"
    else:
        raise AssertionError("missing consent must fail closed")
