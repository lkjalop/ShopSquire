import os
import io
import base64
import pytest
from sqlalchemy import text


def _merchant_key():
    # Match default in auth._role_keys(): MERCHANT_API_KEY default is "local-merchant-key"
    return os.getenv("MERCHANT_API_KEY", "local-merchant-key")


def _tiny_png() -> bytes:
    # 1x1 transparent PNG.
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9s2V9J8AAAAASUVORK5CYII=")


def _ensure_order():
    from src.app.models.db import db_session
    with db_session() as db:
        db.execute(
            text(
                "INSERT OR REPLACE INTO orders "
                "(id, customer_id, guest_email, status, total_cents, created_at) "
                "VALUES (:id, :cust, :guest, 'new', 1000, CURRENT_TIMESTAMP)"
            ),
            {"id": "ord-1", "cust": "cust-123", "guest": "guest@example.com"},
        )
        db.commit()


@pytest.fixture(scope="module")
def app_client():
    from src.app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    return TestClient(app)


def test_upload_ownership_enforced_customer_id(app_client):
    _ensure_order()

    # Prepare a small fake image upload
    files = {"image": ("test.png", io.BytesIO(_tiny_png()), "image/png")}
    params = {"order_id": "ord-1", "customer_id": "cust-123"}
    headers = {"x-api-key": _merchant_key()}

    r = app_client.post("/api/v1/cv/upload", files=files, params=params, headers=headers)
    assert r.status_code in (200, 400)  # Tier0 may reject; ownership should not block when matching
    if r.status_code == 400:
        # If quality gate or processing error fired, it's fine for this test; ownership passed.
        assert "ownership" not in str(r.text).lower()


def test_upload_ownership_mismatch(app_client):
    _ensure_order()
    # Mismatch should yield 403
    files = {"image": ("test.png", io.BytesIO(_tiny_png()), "image/png")}
    params = {"order_id": "ord-1", "customer_id": "cust-XYZ"}
    headers = {"x-api-key": _merchant_key()}
    r = app_client.post("/api/v1/cv/upload", files=files, params=params, headers=headers)
    assert r.status_code == 403
    assert "ownership_mismatch" in r.text


def test_upload_ownership_missing_info(app_client):
    _ensure_order()
    # Missing customer_id/guest_email when order exists should yield 400
    files = {"image": ("test.png", io.BytesIO(_tiny_png()), "image/png")}
    params = {"order_id": "ord-1"}
    headers = {"x-api-key": _merchant_key()}
    r = app_client.post("/api/v1/cv/upload", files=files, params=params, headers=headers)
    assert r.status_code == 400
    assert "ownership_info_required" in r.text
