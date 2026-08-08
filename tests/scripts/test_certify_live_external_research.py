from pathlib import Path

import pytest

from scripts import certify_live_external_research as certification
from src.app.services.recommendation_core.research_contracts import ProviderExecutionReceipt


def test_live_receipt_rejects_fixture_or_missing_network_observations() -> None:
    with pytest.raises(ValueError, match="network execution must be non-fixture"):
        ProviderExecutionReceipt(
            receipt_id="r", execution_id="e",
            provider_capability="WEB_DISCOVERY", provider_id="p",
            certification_run_id="live-run", provider_endpoint_host="localhost",
            query_hash="12345678", execution_status="completed", fixture=True,
            network_execution=True, external_call_dispatched=True,
            cache_status="miss", billing_class="free",
            started_at="2026-08-08T00:00:00Z", completed_at="2026-08-08T00:00:01Z",
            http_status=200, response_body_hash="12345678",
        )


def test_certification_script_is_present() -> None:
    assert Path("scripts/certify_live_external_research.py").is_file()


def _manifest() -> dict:
    return {
        "schema_version": "official-workload-sources-v2",
        "sources": [{
            "source_id": "factory_io_official_docs",
            "publisher": "Real Games",
            "allowed_domains": ["docs.factoryio.com"],
            "canonical_entrypoints": ["https://docs.factoryio.com/manual/system-requirements/"],
            "allowed_claim_types": ["minimum_requirements", "compatibility"],
            "forbidden_claim_types": ["behavioral_performance", "price"],
            "applicability": {
                "workloads": ["factory_io", "plc_simulation"],
                "scope": "Factory I/O host requirements",
                "resolution_owner": "research",
            },
            "artefact_patterns": ["Factory I/O"],
            "parser_type": "html",
            "freshness_sla_hours": 168,
            "publisher_policy": {
                "direct_origin_required": True,
                "policy_ref": "operator:factory-io-docs",
            },
            "cache_policy": {"permitted": True, "max_age_hours": 168},
            "tenant_allowlist": {"default": "deny", "ref": "env:ALLOWLIST"},
            "review_status": "approved",
        }],
    }


def _receipt(capability: str, *, completed: bool = True, results: int = 1) -> dict:
    return {
        "provider_capability": capability,
        "execution_status": "completed" if completed else "failed",
        "fixture": False,
        "network_execution": True,
        "external_call_dispatched": True,
        "cache_status": "miss",
        "query_id": "factory_io_official_docs",
        "allowlisted_result_count": results if capability == "WEB_DISCOVERY" else None,
    }


def _research(
    *, discovery_results: int = 1, origin_completed: bool = True,
    claims: list[dict] | None = None,
) -> dict:
    emitted = claims if claims is not None else [{
        "claim_id": "claim-1",
        "source_id": "factory_io_official_docs",
        "claim_type": "minimum_requirements",
        "attribute": "ram_gb",
    }]
    return {
        "claims": emitted,
        "context_claims": [],
        "unresolved": [] if origin_completed else [{"reason": "origin_failed"}],
        "source_ids": ["factory_io_official_docs"],
        "receipts": [
            _receipt("WEB_DISCOVERY", results=discovery_results),
            _receipt("OFFICIAL_ORIGIN_FETCH", completed=origin_completed),
        ],
        "source_execution": [{
            "source_id": "factory_io_official_docs",
            "origin_selection_mode": "discovered_novel" if discovery_results else "unresolved",
            "discovery_result_count": discovery_results,
        }],
        "provider_accounting": {"external_calls": 2, "paid_calls": 0},
    }


def _run(monkeypatch, tmp_path, research: dict, **kwargs) -> dict:
    monkeypatch.setattr(certification, "load_official_source_manifest", _manifest)
    monkeypatch.setattr(certification, "research_official_sources", lambda *args, **kw: research)
    return certification.certify(
        "http://127.0.0.1:8888/search?q={query}&format=json",
        "I need Factory I/O PLC simulation",
        tmp_path / "certification.json",
        **kwargs,
    )


def test_certification_runs_real_plan_pipeline_and_reports_actual_claims(monkeypatch, tmp_path) -> None:
    artifact = _run(
        monkeypatch, tmp_path, _research(),
        expected_attributes=("ram_gb",),
    )

    assert artifact["certification_status"] == "passed"
    assert artifact["research_plan"]["plan_id"].startswith("crp-")
    assert artifact["claims"][0]["attribute"] == "ram_gb"
    assert artifact["context_claims"] == []
    assert artifact["unresolved"] == []
    assert artifact["paid_calls"] == 0


@pytest.mark.parametrize(
    ("research", "expected_failure"),
    [
        (_research(discovery_results=0), "required_novel_discovery_returned_no_allowlisted_results"),
        (_research(origin_completed=False), "official_origin_unreachable_or_not_network_executed"),
        (_research(claims=[]), "zero_or_insufficient_expected_scoped_claims"),
        (
            _research(claims=[{
                "claim_id": "bad", "source_id": "factory_io_official_docs",
                "claim_type": "behavioral_performance", "attribute": "render_seconds",
            }]),
            "forbidden_claim_emitted",
        ),
    ],
)
def test_certification_fails_closed_for_invalid_live_evidence(
    monkeypatch, tmp_path, research, expected_failure,
) -> None:
    artifact = _run(monkeypatch, tmp_path, research)

    assert artifact["certification_status"] == "failed"
    assert any(expected_failure in row for row in artifact["gate_failures"])


def test_cli_exits_nonzero_when_acceptance_gates_fail(monkeypatch) -> None:
    monkeypatch.setattr(
        certification,
        "certify",
        lambda *args, **kwargs: {"certification_status": "failed", "gate_failures": ["empty"]},
    )
    monkeypatch.setattr("sys.argv", ["certify_live_external_research.py"])

    assert certification.main() == 1
