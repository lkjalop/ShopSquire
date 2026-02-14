import os
import io
import pytest
from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_cv_upload_ownership.db")
os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_cv_upload_ownership.db")


def _merchant_key():
    # Match default in auth._role_keys(): MERCHANT_API_KEY default is "local-merchant-key"
    return os.getenv("MERCHANT_API_KEY", "local-merchant-key")


@pytest.fixture(scope="module")
def app_client():
    from src.app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    return TestClient(app)


def test_upload_ownership_enforced_customer_id(app_client):
    from src.app.models.db import db_session
    # Insert an order
    with db_session() as db:
        db.execute(text("INSERT INTO orders (id, customer_id, guest_email, status, total_cents, created_at) VALUES (:id, :cust, :guest, 'new', 1000, CURRENT_TIMESTAMP)"),
                   {"id": "ord-1", "cust": "cust-123", "guest": "guest@example.com"})
        db.commit()

    # Prepare a small fake image upload
    files = {"image": ("test.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")}
    params = {"order_id": "ord-1", "customer_id": "cust-123"}
    headers = {"x-api-key": _merchant_key()}

    r = app_client.post("/api/v1/cv/upload", files=files, params=params, headers=headers)
    assert r.status_code in (200, 400)  # Tier0 may reject; ownership should not block when matching
    if r.status_code == 400:
        # If quality gate or processing error fired, it's fine for this test; ownership passed.
        assert "ownership" not in str(r.text).lower()


def test_upload_ownership_mismatch(app_client):
    # Mismatch should yield 403
    files = {"image": ("test.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")}
    params = {"order_id": "ord-1", "customer_id": "cust-XYZ"}
    headers = {"x-api-key": _merchant_key()}
    r = app_client.post("/api/v1/cv/upload", files=files, params=params, headers=headers)
    assert r.status_code == 403
    assert "ownership_mismatch" in r.text


def test_upload_ownership_missing_info(app_client):
    # Missing customer_id/guest_email when order exists should yield 400
    files = {"image": ("test.jpg", io.BytesIO(b"fake-bytes"), "image/jpeg")}
    params = {"order_id": "ord-1"}
    headers = {"x-api-key": _merchant_key()}
    r = app_client.post("/api/v1/cv/upload", files=files, params=params, headers=headers)
    assert r.status_code == 400
    assert "ownership_info_required" in r.text
