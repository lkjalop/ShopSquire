import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.models.orm import Base
from tests.utils import default_headers


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    schema = pathlib.Path("db/schema.sql")
    if schema.exists():
        with engine.connect() as conn:
            for statement in [row.strip() for row in schema.read_text(encoding="utf-8").split(";") if row.strip()]:
                try:
                    conn.execute(text(statement))
                except Exception:
                    pass
            conn.commit()
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    engine = _engine()
    import src.app.models.db as dbmod
    original = dbmod.engine
    dbmod.engine = engine
    dbmod.set_engine(engine)
    with engine.begin() as conn:
        for sku, name, price, stock in (
            ("PREFERRED", "Preferred exact configuration", 500_000, 12),
            ("SUBSTITUTE", "Explicit compatible substitute", 450_000, 30),
        ):
            product_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO products (id, sku, name, price_cents, active) "
                "VALUES (:id, :sku, :name, :price, 1)"
            ), {"id": product_id, "sku": sku, "name": name, "price": price})
            conn.execute(text(
                "INSERT INTO inventory (id, product_id, stock, warehouse) "
                "VALUES (:id, :product, :stock, 'default')"
            ), {"id": str(uuid.uuid4()), "product": product_id, "stock": stock})
        conn.execute(text(
            "INSERT INTO shopping_cases "
            "(id, case_id, tenant_id, uid, status, retained_purpose, revision) "
            "VALUES (:id, 'sc-supplier-1', 'default', 'buyer-1', 'active', 'same case', 1)"
        ), {"id": str(uuid.uuid4())})
    from src.app.main import create_app
    app = create_app()
    app.state.engine = engine

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with TestClient(app, headers=default_headers(), raise_server_exceptions=False) as test_client:
        yield test_client, engine
    dbmod.engine = original
    dbmod.set_engine(original)


def _select(client: TestClient, *, key: str = "select-supplier-1") -> dict:
    response = client.post(
        "/api/v1/shopping-cases/sc-supplier-1/fulfillment-selections",
        headers={"Idempotency-Key": key},
        json={
            "uid": "buyer-1", "expected_revision": 0, "choice": "substitute",
            "preferred_sku": "PREFERRED", "substitute_sku": "SUBSTITUTE",
            "requested_quantity": 30, "available_now": 12,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_same_case_offer_selection_and_cart_confirmation_are_exactly_once(client) -> None:
    http, engine = client
    selection = _select(http)
    replay = _select(http)
    assert replay["selection_id"] == selection["selection_id"]
    assert selection["supplier_send"] == "not_performed"
    assert selection["procurement_decision_run"]["persistence_status"] == "persisted"
    assert selection["procurement_decision_run"]["commercial_authority_granted"] is False
    history = http.get(
        "/api/v1/shopping-cases/sc-supplier-1/decision-runs?uid=buyer-1",
    )
    assert history.status_code == 200, history.text
    assert history.json()["history_count"] == 1
    assert {row["stage"] for row in history.json()["latest"]["stage_receipts"]} == {
        "commercial", "fulfilment", "response",
    }
    assert history.json()["dependency_edges"]
    substitute = next(row for row in selection["offers"] if row["relationship"] == "compatible_substitute")

    rejected = http.post(
        f"/api/v1/shopping-cases/sc-supplier-1/fulfillment-selections/{selection['selection_id']}/confirm-cart",
        headers={"Idempotency-Key": "reject-silent-substitute-1"},
        json={
            "uid": "buyer-1", "expected_revision": selection["revision"],
            "selected_offer_id": substitute["offer_id"], "substitution_authorized": False,
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "substitution_requires_explicit_authorization"

    first = http.post(
        f"/api/v1/shopping-cases/sc-supplier-1/fulfillment-selections/{selection['selection_id']}/confirm-cart",
        headers={"Idempotency-Key": "confirm-supplier-1"},
        json={
            "uid": "buyer-1", "expected_revision": selection["revision"],
            "selected_offer_id": substitute["offer_id"], "substitution_authorized": True,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["confirmed_sku"] == "SUBSTITUTE"
    assert first.json()["confirmed_quantity"] == 30
    assert first.json()["supplier_offer_provenance"] == substitute["provenance"]
    second = http.post(
        f"/api/v1/shopping-cases/sc-supplier-1/fulfillment-selections/{selection['selection_id']}/confirm-cart",
        headers={"Idempotency-Key": "confirm-supplier-1"},
        json={
            "uid": "buyer-1", "expected_revision": selection["revision"],
            "selected_offer_id": substitute["offer_id"], "substitution_authorized": True,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["cart_plan_id"] == first.json()["cart_plan_id"]
    cart = http.get("/api/v1/cart", params={"uid": "buyer-1"}).json()
    assert [(row["sku"], row["quantity"]) for row in cart["items"]] == [("SUBSTITUTE", 30)]
    with engine.connect() as conn:
        selection_count = conn.execute(text(
            "SELECT COUNT(*) FROM shopping_case_fulfillment_selections WHERE case_id='sc-supplier-1'"
        )).scalar_one()
        plan_count = conn.execute(text(
            "SELECT COUNT(*) FROM cart_mutation_plans WHERE trace_id='supplier-1'"
        )).scalar_one()
    assert selection_count == 1
    assert plan_count == 1
