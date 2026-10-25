import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.app.models.orm import Base, Product
from src.app.models.db import get_db
from src.app.routers.demo import router
from src.app.services.electronics_shop_scenario import seed_scenario
from src.app.services.inventory_transactions import ensure_tables
from src.app.services.portfolio_qualification import seed_configuration, create_case, TENANT
from tests.buyer_client import BuyerTestClient, TEST_SIGNING_KEY


def test_demo_acceptance_is_owned_explicit_revision_bound_and_replay_safe(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", TEST_SIGNING_KEY)
    monkeypatch.setenv(
        "BUYER_TENANT_BINDINGS_JSON",
        '{"buyer":["synthetic-electronics"],"other":["synthetic-electronics"]}',
    )
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ensure_tables(db)
        db.add(
            Product(sku="LAP-existing", name="Snapshot", price_cents=150000, specs={"ram_gb": 32})
        )
        seed_scenario(db, tenant_id=TENANT, sku="LAP-existing", retail_cents=150000)
        db.flush()
        seed_configuration(db)
        case = create_case(db, uid="buyer")
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id

        @app.middleware("http")
        async def tenant_context(request, call_next):
            token = set_active_tenant_id(request.headers.get("x-tenant-id"))
            try:
                return await call_next(request)
            finally:
                reset_active_tenant_id(token)

        path = "/api/v1/demo/qualification-cases/" + case["case_id"]
        body = dict(uid="buyer", expected_revision=1, quantity=30, idempotency_key="accept-30")
        with BuyerTestClient(app, headers={"X-Tenant-ID": TENANT}) as client:
            monkeypatch.setenv("ENABLE_DEMO_ROUTES", "0")
            assert client.post(path + "/stock-acceptance", json=body).status_code == 404
            monkeypatch.setenv("ENABLE_DEMO_ROUTES", "1")
            assert (
                client.post(
                    path + "/stock-acceptance", json=body, headers={"Authorization": ""}
                ).status_code
                == 401
            )
            assert (
                client.post(path + "/stock-acceptance", json={**body, "uid": "other"}).status_code
                == 403
            )
            assert (
                client.post(path + "/stock-acceptance", json={**body, "quantity": True}).status_code
                == 422
            )
            response = client.post(path + "/stock-acceptance", json=body)
            assert response.status_code == 200
            assert response.json()["held_quantity"] == 15
            assert response.json()["purchase_commitment"] is False
            assert client.post(path + "/stock-acceptance", json=body).json() == response.json()
            assert (
                client.post(path + "/stock-acceptance", json={**body, "quantity": 40}).status_code
                == 409
            )
            amended = client.post(
                path + "/stock-acceptance",
                json={
                    **body,
                    "quantity": 40,
                    "expected_revision": 2,
                    "idempotency_key": "accept-40",
                },
            )
            assert amended.status_code == 200
            assert amended.json()["shortfall"] == 25
            snapshot = client.get(path + "/stock", params={"uid": "buyer"}).json()
            assert snapshot["available"] == 0
            assert snapshot["accepted"]["requested_quantity"] == 40
            assert snapshot["accepted"]["hold_expires_at"]
            from sqlalchemy import text

            db.execute(
                text(
                    "UPDATE inventory_reservation SET expires_at='2020-01-01T00:00:00+00:00' WHERE status='reserved'"
                )
            )
            db.commit()
            expired = client.get(path + "/stock", params={"uid": "buyer"}).json()
            assert expired["accepted"]["held_quantity"] == 0
            assert expired["accepted"]["shortfall"] == 40
            # Reading does not mutate stock; the explicit release can still free expired holds.
            assert expired["available"] == 0
            released = client.post(
                path + "/release-holds", json=dict(uid="buyer", expected_revision=3)
            )
            assert released.status_code == 200
            assert client.get(path + "/stock", params={"uid": "buyer"}).json()["available"] == 15
    engine.dispose()
