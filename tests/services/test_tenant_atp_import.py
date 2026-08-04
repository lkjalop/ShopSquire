from types import SimpleNamespace

import pytest

from src.app.services.authoritative_business_feed import BusinessObservation
from src.app.services import tenant_atp_import as subject


def _observation(entity="location_atp"):
    return BusinessObservation(
        entity_type=entity, external_id="ATP-1", event_time="2026-08-02T00:00:00Z",
        payload={},
    )


def test_tenant_atp_import_composes_append_only_feed_and_shadow_projection(monkeypatch):
    calls = {}
    monkeypatch.setattr(subject, "load_observations_csv", lambda path: [_observation()])
    monkeypatch.setattr(
        subject, "ingest_authoritative_observations",
        lambda **kwargs: calls.setdefault("feed", kwargs) or {},
    )
    calls["feed_result"] = None

    def _ingest(**kwargs):
        calls["feed"] = kwargs
        return {"status": "observed", "records_inserted": 1}

    monkeypatch.setattr(subject, "ingest_authoritative_observations", _ingest)
    session = SimpleNamespace(commit=lambda: calls.setdefault("committed", True))

    class _Context:
        def __enter__(self): return session
        def __exit__(self, *args): return False

    monkeypatch.setattr(subject, "db_session", _Context)
    monkeypatch.setattr(
        subject, "sync_authoritative_location_atp",
        lambda db, **kwargs: {"status": "ready", "applied": [{"snapshot_version": "v1"}],
                              "rejected": []},
    )
    result = subject.import_tenant_location_atp_csv(
        "tenant.csv", tenant_id="tenant-a", source="partner-wms",
    )
    assert calls["feed"]["tenant_id"] == "tenant-a"
    assert calls["feed"]["source"] == "partner-wms"
    assert result["status"] == "projected"
    assert result["execution_authority"] == "shadow_allocation_only"


def test_tenant_atp_import_rejects_mixed_entity_file_before_any_write(monkeypatch):
    monkeypatch.setattr(subject, "load_observations_csv", lambda path: [_observation("order_line")])
    monkeypatch.setattr(
        subject, "ingest_authoritative_observations",
        lambda **kwargs: pytest.fail("mixed file must not reach the ledger"),
    )
    with pytest.raises(ValueError, match="non_atp_entities:order_line"):
        subject.import_tenant_location_atp_csv(
            "mixed.csv", tenant_id="tenant-a", source="partner-wms",
        )
