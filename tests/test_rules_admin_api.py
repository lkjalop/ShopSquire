import json

from fastapi.testclient import TestClient

from src.app.main import create_app


def _owner_headers() -> dict:
    return {"x-api-key": "local-owner-key"}


def test_rules_crud_and_preview():
    app = create_app()
    client = TestClient(app)

    # Create
    create_payload = {
        "title": "Intent: product_search",
        "domain": "recommend",
        "pattern": r"(?i)\bshow\s+me\b",
        "priority": 10,
        "active": 1,
    }
    r = client.post("/api/v1/rules/", headers=_owner_headers(), content=json.dumps(create_payload))
    assert r.status_code == 200
    rid = r.json().get("id")
    assert rid

    # List
    r = client.get("/api/v1/rules/?domain=recommend", headers=_owner_headers())
    assert r.status_code == 200
    rows = r.json().get("rules") or []
    assert any(x.get("id") == rid for x in rows)

    # Preview should match our rule
    r = client.post("/api/v1/rules/preview", headers=_owner_headers(), content=json.dumps({"text": "show me laptops", "domain": "recommend"}))
    assert r.status_code == 200
    out = r.json().get("preview") or {}
    assert out.get("handled") is True
    assert out.get("rule_id") == rid

    # Update
    r = client.put(f"/api/v1/rules/{rid}", headers=_owner_headers(), content=json.dumps({"priority": 5}))
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # Delete
    r = client.delete(f"/api/v1/rules/{rid}", headers=_owner_headers())
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_rules_rejects_invalid_regex():
    app = create_app()
    client = TestClient(app)
    bad = {"title": "bad", "domain": "recommend", "pattern": r"(", "priority": 10, "active": 1}
    r = client.post("/api/v1/rules/", headers=_owner_headers(), content=json.dumps(bad))
    assert r.status_code == 400

