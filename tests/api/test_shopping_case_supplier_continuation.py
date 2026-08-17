import pathlib
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.models.db import get_db
from src.app.models.orm import Base
from src.app.security.idempotency import IdempotencyMiddleware
from tests.utils import default_headers


def _engine(database_path: pathlib.Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}", future=True,
        connect_args={"check_same_thread": False},
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
def client(monkeypatch, tmp_path):
    database_path = tmp_path / "supplier-continuation.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    engine = _engine(database_path)
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
    # This suite certifies the endpoint's durable, case-revision-bound
    # idempotency records.  The global HTTP middleware uses the process's
    # operational database and is covered separately; leaving both active in
    # an in-memory fixture can replay a response from a prior ephemeral DB.
    app.user_middleware = [
        row for row in app.user_middleware if row.cls is not IdempotencyMiddleware
    ]
    app.middleware_stack = app.build_middleware_stack()

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
            "uid": "buyer-1", "expected_revision": 1, "choice": "substitute",
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
    assert selection["revision"] == 2
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
    assert history.json()["views"]["what_changed"]["to_revision"] == 2
    assert history.json()["views"]["what_was_known_then"]["future_evidence_excluded"] is True
    fulfilment_view = history.json()["views"]["who_can_fulfil_now"]
    assert fulfilment_view["requested_quantity"] == 30
    assert fulfilment_view["supplier_candidates"]
    assert "not a live stock promise" in fulfilment_view["evidence_warning"]
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT revision FROM shopping_cases WHERE case_id='sc-supplier-1'"
        )).scalar_one() == 2
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
    assert first.json()["revision"] == 3
    assert first.json()["procurement_decision_run"]["case_revision"] == 3
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
        case_revision = conn.execute(text(
            "SELECT revision FROM shopping_cases WHERE case_id='sc-supplier-1'"
        )).scalar_one()
        selection_count = conn.execute(text(
            "SELECT COUNT(*) FROM shopping_case_fulfillment_selections WHERE case_id='sc-supplier-1'"
        )).scalar_one()
        plan_count = conn.execute(text(
            "SELECT COUNT(*) FROM cart_mutation_plans WHERE trace_id='supplier-1'"
        )).scalar_one()
    assert selection_count == 1
    assert plan_count == 1
    assert case_revision == 3


def test_real_inventory_observation_advances_case_and_selectively_recomputes(client) -> None:
    http, engine = client
    selection = _select(http, key="select-before-stock-correction")
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "observation_id": "inventory-correction-0001",
        "expected_revision": selection["revision"],
        "kind": "inventory_quantity",
        "subject_ref": "configuration:PREFERRED",
        "location_ref": "warehouse:nearest-eligible",
        "value": {"quantity": 4, "unit": "unit"},
        "source_type": "inventory_system",
        "evidence_ref": "inventory-ledger:row-44",
        "known_at": now,
        "effective_at": now,
    }
    observed = http.post(
        "/api/v1/shopping-cases/sc-supplier-1/operational-observations",
        json=payload,
    )
    assert observed.status_code == 201, observed.text
    result = observed.json()
    assert result["case_revision"] == 3
    assert result["changed_ref"] == "inventory:current"
    assert result["recomputed_stages"] == ["commercial", "fulfilment", "response"]
    assert result["operational_projection"] == {
        "kind": "inventory_quantity", "available_now": 4,
        "requested_quantity": 30, "remaining_quantity": 26,
        "quantity_outcome": "shortfall",
    }
    assert result["external_calls"] == result["rfq_calls"] == result["cart_mutations"] == 0
    replay = http.post(
        "/api/v1/shopping-cases/sc-supplier-1/operational-observations",
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True

    history = http.get(
        "/api/v1/shopping-cases/sc-supplier-1/decision-runs?uid=buyer-1",
    ).json()
    assert history["history_count"] == 2
    assert history["latest"]["case_revision"] == 3
    assert history["latest"]["invalidations"][0]["changed_path"] == "fulfilment.inventory"
    assert history["views"]["what_changed"]["from_revision"] == 2
    assert history["views"]["what_changed"]["to_revision"] == 3
    assert history["views"]["who_can_fulfil_now"]["available_now"] == 4
    assert history["history"][0]["case_revision"] == 2

    stale_confirmation = http.post(
        f"/api/v1/shopping-cases/sc-supplier-1/fulfillment-selections/{selection['selection_id']}/confirm-cart",
        headers={"Idempotency-Key": "stale-after-inventory-correction"},
        json={
            "uid": "buyer-1",
            "expected_revision": selection["revision"],
            "selected_offer_id": None,
            "substitution_authorized": False,
        },
    )
    assert stale_confirmation.status_code == 409
    assert stale_confirmation.json()["detail"]["code"] == "stale_case_revision"
    assert http.get("/api/v1/cart", params={"uid": "buyer-1"}).json()["items"] == []
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM shopping_case_operational_observations"
        )).scalar_one() == 1


@pytest.mark.parametrize(("kind", "value", "changed_ref"), [
    ("price", {"amount_cents": 525_000, "currency": "AUD"}, "price:current"),
    ("supplier_lead_time", {"days": 14}, "delivery:observations"),
    ("quote_validity", {"valid_until": "2026-08-31T00:00:00+00:00"}, "supplier:offers"),
    ("supplier_response", {"status": "rejected"}, "supplier:offers"),
])
def test_operational_fact_classes_are_append_only_and_non_authoritative(
    client, kind, value, changed_ref,
) -> None:
    http, engine = client
    selection = _select(http, key=f"select-before-{kind}")
    now = datetime.now(timezone.utc).isoformat()
    response = http.post(
        "/api/v1/shopping-cases/sc-supplier-1/operational-observations",
        json={
            "observation_id": f"operational-{kind}-0001",
            "expected_revision": selection["revision"],
            "kind": kind,
            "subject_ref": "configuration:PREFERRED",
            "location_ref": "facility:eligible",
            "value": value,
            "source_type": "supplier" if kind.startswith("supplier") else "human_admin",
            "evidence_ref": f"operator-ledger:{kind}",
            "known_at": now,
            "effective_at": now,
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["changed_ref"] == changed_ref
    assert result["recomputed_stages"] == ["commercial", "fulfilment", "response"]
    assert result["commercial_authority_granted"] is False
    with engine.connect() as conn:
        stored = conn.execute(text(
            "SELECT kind, value_json FROM shopping_case_operational_observations"
        )).one()
    assert stored[0] == kind
    assert stored[1]
