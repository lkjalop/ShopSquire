from fastapi.testclient import TestClient


def test_cv_upload_rejects_executable_payload():
    from src.app.main import create_app

    client = TestClient(create_app())
    files = {
        "image": ("evil.exe", b"MZ-fake-pe", "application/x-msdownload"),
    }
    r = client.post("/api/v1/cv/upload", files=files, headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else {}
    assert detail.get("error") == "ingest_gate_blocked"


def test_storefront_submit_rejects_executable_image():
    from src.app.main import create_app

    client = TestClient(create_app())
    data = {
        "order_id": "ord-demo-1",
        "issue_type": "damaged",
        "description": "broken",
    }
    files = [
        ("images", ("overlay.exe", b"MZ-fake-pe", "application/x-msdownload")),
    ]
    r = client.post("/api/v1/support/complaints/submit", data=data, files=files, headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") if isinstance(body, dict) else {}
    assert detail.get("error") == "ingest_gate_blocked"

