from pathlib import Path

import yaml


def test_pilot_alert_manifest_covers_runtime_failure_classes() -> None:
    path = Path("config/observability/portfolio_pilot_alerts.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    alerts = {
        rule["alert"]: rule["expr"]
        for group in payload["groups"]
        for rule in group["rules"]
    }
    assert "ShopSquireModelTimeouts" in alerts
    assert "ShopSquireModelArtifactMismatch" in alerts
    assert "ShopSquireAgentLedgerPersistenceFailure" in alerts
    assert "ShopSquireDiscoveryFailureOrZeroResults" in alerts
    assert "ShopSquireOfficialParserFailure" in alerts
    assert "ShopSquireCarrierTimeout" in alerts
    assert "ShopSquireDatabasePoolSaturation" in alerts
    assert "ShopSquireCommerceIdempotencyConflict" in alerts
    assert all("buyer" not in expression.lower() for expression in alerts.values())
