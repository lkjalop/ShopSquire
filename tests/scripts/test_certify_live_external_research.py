from pathlib import Path

import pytest

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
