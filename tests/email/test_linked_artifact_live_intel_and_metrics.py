from __future__ import annotations

from typing import Any


def _counter_value(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


def test_linked_artifact_adds_domain_age_and_supplier_verification(monkeypatch):
    from src.app.security import linked_artifact_analysis as mod

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "events": [
                    {
                        "eventAction": "registration",
                        "eventDate": "2024-01-15T00:00:00Z",
                    }
                ]
            }

    real_safe_request = mod.safe_request

    def _fake_safe_request(method: str, url: str, **kwargs):
        if "rdap.org/domain/" in url:
            return _Resp()
        return real_safe_request(method, url, **kwargs)

    monkeypatch.setattr(mod, "safe_request", _fake_safe_request, raising=True)
    monkeypatch.setattr(
        mod,
        "get_supplier_governance_profile",
        lambda **_kwargs: {
            "approved_domains": ["ingram-verify-test.com"],
            "approved_bank_fingerprints": [],
            "pending_updates": [],
            "governance_state": "stable",
        },
        raising=True,
    )
    monkeypatch.setattr(mod, "_extract_bank_fields", lambda _text: {}, raising=True)
    monkeypatch.setattr(mod, "_bank_fingerprint", lambda _fields: None, raising=True)

    out = mod.analyze_linked_artifact(
        url="https://ingram-verify-test.com/payment/verify?inv=INV-2026-00847",
        tenant_id="email-sec-live-intel",
        vendor_domain="ingram-verify-test.com",
    )
    host = out.get("linked_host_enrichment") or {}
    supplier = out.get("linked_supplier_verification") or {}
    assert host.get("registration_source") == "rdap.org"
    assert isinstance(host.get("domain_age_days"), int)
    assert supplier.get("approved_supplier_domain") is True
    assert supplier.get("verification_status") == "verified_supplier_destination"
    assert out.get("linked_verdict_label") == "Verified"


def test_unresolved_linked_artifact_records_release_metrics(monkeypatch):
    from src.app.observability.metrics import (
        linked_artifact_fetch_total,
        linked_artifact_unresolved_total,
        linked_artifact_verdict_total,
    )
    from src.app.security import linked_artifact_analysis as mod

    tenant = "email-sec-metrics"
    unresolved_reason = "linked_fetch_failed"
    before_fetch = _counter_value(linked_artifact_fetch_total, tenant_id=tenant, status="unresolved", source="live_url")
    before_unresolved = _counter_value(linked_artifact_unresolved_total, tenant_id=tenant, reason=unresolved_reason)
    before_verdict = _counter_value(linked_artifact_verdict_total, tenant_id=tenant, verdict="Unverified Destination")

    def _raise_for_fetch(method: str, url: str, **kwargs):
        if "rdap.org/domain/" in url:
            raise RuntimeError("forced_unresolved")
        raise RuntimeError("forced_unresolved")

    monkeypatch.setattr(mod, "safe_request", _raise_for_fetch, raising=True)
    out = mod.analyze_linked_artifact(
        url="https://billing-verify-example.invalid/payment/verify?invoice=98765",
        tenant_id=tenant,
        timeout=2.0,
    )

    after_fetch = _counter_value(linked_artifact_fetch_total, tenant_id=tenant, status="unresolved", source="live_url")
    after_unresolved = _counter_value(linked_artifact_unresolved_total, tenant_id=tenant, reason=unresolved_reason)
    after_verdict = _counter_value(linked_artifact_verdict_total, tenant_id=tenant, verdict="Unverified Destination")

    assert out["linked_verdict_label"] == "Unverified Destination"
    assert after_fetch == before_fetch + 1.0
    assert after_unresolved == before_unresolved + 1.0
    assert after_verdict == before_verdict + 1.0
