from __future__ import annotations

from contextlib import contextmanager

from src.app.platform import tenant_registry
from src.app.tasks import market_signal_tasks


def test_canonical_tenants_require_explicit_configuration(monkeypatch):
    monkeypatch.delenv("MARKET_CANONICAL_TENANTS", raising=False)
    monkeypatch.delenv("STORE_TENANT_REGISTRY_JSON", raising=False)
    monkeypatch.delenv("STORE_TENANT_REGISTRY_PATH", raising=False)
    tenant_registry.reset_cache()

    assert market_signal_tasks._canonical_tenant_ids() == ()
    assert market_signal_tasks._canonical_tenant_ids("tenant-explicit") == ("tenant-explicit",)


def test_canonical_tenants_are_deduplicated_and_bounded(monkeypatch):
    monkeypatch.setenv("MARKET_CANONICAL_TENANTS", "tenant-b, tenant-a,tenant-b")
    assert market_signal_tasks._canonical_tenant_ids() == ("tenant-b", "tenant-a")


def test_registry_exposes_configured_tenants(monkeypatch):
    monkeypatch.delenv("MARKET_CANONICAL_TENANTS", raising=False)
    monkeypatch.setenv(
        "STORE_TENANT_REGISTRY_JSON",
        '{"tenants":{"tenant-b":{"profile":"au"},"tenant-a":{"profile":"us"}}}',
    )
    tenant_registry.reset_cache()
    assert tenant_registry.registered_tenant_ids() == ("tenant-a", "tenant-b")
    assert tenant_registry.tenant_config("tenant-a")["store_profile_id"] == "us"
    assert market_signal_tasks._canonical_tenant_ids() == ("tenant-a", "tenant-b")


def test_canonical_backfill_fans_out_with_explicit_tenant_identity(monkeypatch):
    monkeypatch.setenv("MARKET_CANONICAL_FACTS_ENABLED", "1")
    monkeypatch.delenv("MARKET_SIGNAL_BACKFILL_ENABLED", raising=False)
    monkeypatch.setenv("MARKET_CANONICAL_TENANTS", "tenant-a,tenant-b")
    calls = []

    class FakeDb:
        def commit(self):
            calls.append(("commit", None))

    @contextmanager
    def fake_session():
        yield FakeDb()

    def fake_backfill(db, *, tenant_id, limit, commit):
        calls.append((tenant_id, commit))
        return {"tenant_id": tenant_id, "written": 1, "quarantined": 0}

    monkeypatch.setattr("src.app.models.db.db_session", fake_session)
    monkeypatch.setattr(
        "src.app.services.canonical_fact_adapters.backfill_canonical_facts", fake_backfill
    )

    result = market_signal_tasks.market_signal_backfill.run()

    assert calls == [("tenant-a", False), ("tenant-b", False), ("commit", None)]
    assert result["canonical_facts"]["written"] == 2
    assert set(result["canonical_facts"]["tenants"]) == {"tenant-a", "tenant-b"}
