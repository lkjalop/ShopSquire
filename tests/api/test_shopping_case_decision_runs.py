from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.models.orm import Base, ShoppingCase
from src.app.routers.shopping_cases import router
from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_run import (
    StageReceipt,
    create_decision_run,
    create_decision_snapshot,
    persist_decision_run,
)


def _client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ShoppingCase(
            case_id="case-trace", tenant_id="portfolio", uid="buyer", status="active",
        ))
        state = ProcurementCaseState(case_id="case-trace", revision=2, objective="fleet")
        snapshot = create_decision_snapshot(state, tenant_id="portfolio")
        moment = datetime.now(timezone.utc).isoformat()
        run = create_decision_run(
            snapshot, idempotency_key="trace:one", status="completed",
            stage_receipts=(StageReceipt(
                stage="commercial", stage_id="stage-commercial", status="completed",
                started_at=moment, completed_at=moment,
                input_hash="a" * 64, output_hash="b" * 64,
                input_artifact_refs=("inventory:current",),
                output_artifact_refs=("commercial:shelves",),
            ),),
        )
        persist_decision_run(db, run)
    app = FastAPI()
    app.include_router(router)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    return TestClient(app)


def test_owner_can_read_revisioned_decision_trace_without_commerce_authority():
    response = _client().get(
        "/api/v1/shopping-cases/case-trace/decision-runs?uid=buyer",
        headers={"X-Tenant-Id": "portfolio"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["history_count"] == 1
    assert body["latest"]["case_revision"] == 2
    assert body["latest"]["commercial_authority_granted"] is False
    assert body["dependency_edges"][0]["run_id"] == body["latest"]["run_id"]


def test_other_buyer_cannot_read_decision_trace():
    response = _client().get(
        "/api/v1/shopping-cases/case-trace/decision-runs?uid=intruder",
        headers={"X-Tenant-Id": "portfolio"},
    )
    assert response.status_code == 403
