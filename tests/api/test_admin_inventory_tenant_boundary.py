from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.routers import admin_inventory


WRITES = [
    ("/sync", {"connector": "csv"}),
    ("/sync/netsuite/delta", {}),
    ("/sync/netsuite/outbound/enqueue", {"entity_type": "customer", "payload": {}}),
    ("/sync/netsuite/outbound/run", {}),
    ("/sync/erp/delta", {"provider": "sap"}),
    ("/sync/erp/outbound/enqueue", {"provider": "sap", "entity_type": "customer", "payload": {}}),
    ("/sync/erp/outbound/run", {"provider": "sap"}),
]
READS = ["/connectors/summary", "/sync/runs", "/external_stock/recent"]
ROOT = "/api/v1/admin/inventory"


@pytest.fixture
def inventory_actor(owned_operator_client, monkeypatch):
    client, headers = owned_operator_client("inventory-owned")
    calls = []

    def effect(*args, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    connector = SimpleNamespace(health=lambda: {"ok": True}, name=lambda: "fixture", subscription_id="fixture",
                                fetch_inventory_delta=lambda **kwargs: ([], None))
    monkeypatch.setattr(admin_inventory, "_load_csv_connector", lambda *args, **kwargs: connector)
    monkeypatch.setattr(admin_inventory, "_load_shopify_connector", lambda: connector)
    monkeypatch.setattr(admin_inventory, "_load_external_connector", lambda *args: connector)
    monkeypatch.setattr(admin_inventory, "load_provider", lambda *args: connector)
    monkeypatch.setattr(admin_inventory, "get_cursor_state", lambda **kwargs: SimpleNamespace(cursor=None, version=0))
    for name in ["run_netsuite_delta_sync", "run_netsuite_outbound_sync", "enqueue_netsuite_outbound", "sync_inventory"]:
        monkeypatch.setattr(admin_inventory, name, effect)
    monkeypatch.setattr("src.app.erp.sync.sync_inventory", effect)
    monkeypatch.setattr("src.app.erp.jobs_generic.enqueue_outbound", effect)
    monkeypatch.setattr("src.app.erp.jobs_generic.run_outbound", effect)
    return client, headers, calls


@pytest.mark.parametrize("path,payload", WRITES)
def test_inventory_write_rejects_foreign_body_before_effects(inventory_actor, path, payload):
    client, headers, calls = inventory_actor
    response = client.post(ROOT + path, headers=headers, json={**payload, "tenant_id": "inventory-foreign"})
    assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize("path,payload", WRITES)
@pytest.mark.parametrize("explicit_tenant", [True, False])
def test_inventory_write_passes_only_authorized_scope(inventory_actor, path, payload, explicit_tenant):
    client, headers, calls = inventory_actor
    body = {**payload, **({"tenant_id": headers["x-tenant-id"]} if explicit_tenant else {})}
    response = client.post(ROOT + path, headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert calls
    assert all(call.get("tenant_id") == headers["x-tenant-id"] for call in calls)


@pytest.mark.parametrize("path", READS)
def test_inventory_read_rejects_foreign_query(inventory_actor, path):
    client, headers, _ = inventory_actor
    response = client.get(ROOT + path, headers=headers, params={"tenant_id": "inventory-foreign"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", READS)
def test_inventory_read_allows_owned_scope(inventory_actor, path):
    client, headers, _ = inventory_actor
    response = client.get(ROOT + path, headers=headers, params={"tenant_id": headers["x-tenant-id"]})
    assert response.status_code == 200, response.text


def test_inventory_summary_samples_cannot_mix_tenants_when_scope_is_omitted(inventory_actor):
    client, headers, _ = inventory_actor
    marker = uuid.uuid4().hex
    rows = [{"id": marker + "-owned", "tenant": headers["x-tenant-id"], "sku": marker + "-owned"},
            {"id": marker + "-foreign", "tenant": "inventory-foreign", "sku": marker + "-foreign"}]
    with Session(client.app.state.engine) as db:
        db.execute(text("INSERT INTO inventory_external_stock (id,tenant_id,source,sku,warehouse,stock) "
                        "VALUES (:id,:tenant,'csv',:sku,'test',1)"), rows)
        db.commit()
    try:
        response = client.get(ROOT + "/connectors/summary", headers=headers)
        assert response.status_code == 200, response.text
        samples = next(item["sample"] for item in response.json()["items"] if item["id"] == "csv")
        assert {item["sku"] for item in samples} == {marker + "-owned"}
    finally:
        with Session(client.app.state.engine) as db:
            db.execute(text("DELETE FROM inventory_external_stock WHERE id IN (:owned,:foreign)"),
                       {"owned": marker + "-owned", "foreign": marker + "-foreign"})
            db.commit()
