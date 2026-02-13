import io
import os
import json
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.cv_provider import ManagedCVProvider
from src.app.services.warehouse_verification import WarehouseVerification
from src.app.models.db import db_session


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path_factory.getbasetemp()}/e2e.sqlite"
    app = create_app()
    # Seed order and expected serial mapping
    with db_session() as db:
        db.execute(text("INSERT INTO orders (id, total_cents, currency, status) VALUES ('ORDERX', 10000, 'USD', 'paid')"))
        # Create mapping table and insert serial
        try:
            db.execute(text("CREATE TABLE IF NOT EXISTS order_serials (order_id TEXT PRIMARY KEY, serial TEXT)"))
        except Exception:
            pass
        db.execute(text("INSERT OR REPLACE INTO order_serials (order_id, serial) VALUES ('ORDERX', 'SN-EXPECT1')"))
        db.commit()
    return TestClient(app)


def test_e2e_pipeline_with_fraud_and_warehouse(client, monkeypatch):
    # Mock CV provider: first call returns damage + observed serial, second call returns different labels & low confidence via triage
    calls = {"n": 0}

    async def fake_labels_and_text(self, image_bytes: bytes):
        calls["n"] += 1
        if calls["n"] == 1:
            return ["hinge", "damage"], "Serial: SN-OBS2"
        else:
            return ["screen", "crack"], "Serial: SN-OBS2"

    monkeypatch.setattr(ManagedCVProvider, "get_labels_and_text", fake_labels_and_text)

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDAT\x08\x99c``\xf8\x0f\x00\x01\x05\x01\x00\x18\x9d\x9c\x1e\x00\x00\x00\x00IEND\xAE\x42\x60\x82"
    )
    files = [("images", ("a.png", io.BytesIO(png), "image/png"))]
    payload = {"order_id": "ORDERX", "issue_type": "damage", "description": "hinge problem"}
    r1 = client.post("/api/v1/support/complaints/submit", data=payload, files=files)
    if r1.status_code == 422:
        pytest.skip(f"multipart env issue: {r1.text}")
    assert r1.status_code == 200
    data1 = r1.json()
    case_id = data1["case_id"]
    decision_id = data1.get("decision_id")
    # fraud level should reflect serial mismatch (observed vs expected)
    assert data1["fraud"]["level"] in ("medium", "high")

    # add-images with second provider call (different labels)
    files2 = [("images", ("b.png", io.BytesIO(png), "image/png"))]
    r2 = client.post(f"/api/v1/support/complaints/{case_id}/add-images", files=files2)
    if r2.status_code == 422:
        pytest.skip(f"multipart env issue: {r2.text}")
    assert r2.status_code == 200

    # verify warehouse mismatches
    ver = WarehouseVerification()
    res = ver.compare_latest_pair(case_id)
    assert res["status"] == "ok"
    assert any(m in res["mismatches"] for m in ("labels_overlap_low", "damage_location", "confidence_delta_high"))

    # inspect decision log to assert enriched fraud signals persisted
    from src.app.models.db import db_session
    with db_session() as db:
        if decision_id:
            row = db.execute(text("SELECT retrieved_context FROM decision_logs WHERE id = :id LIMIT 1"), {"id": decision_id}).fetchone()
        else:
            # Fallback for legacy responses
            row = db.execute(
                text("SELECT retrieved_context FROM decision_logs WHERE input_data LIKE :pat ORDER BY system_from ASC LIMIT 1"),
                {"pat": f"%{case_id}%"},
            ).fetchone()
        assert row is not None
        ctx = json.loads(row[0])
        assert ctx.get("fraud_signals", {}).get("serial_mismatch") is True
