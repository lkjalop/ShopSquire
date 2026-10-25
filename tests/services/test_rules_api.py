import uuid

from src.app.routers.rules import store


def test_rules_crud_and_preview(owned_operator_client):
    client, headers = owned_operator_client("rules-crud", role="developer")
    other_client, other_headers = owned_operator_client("rules-crud-other", role="developer")
    rid = "rule-api-" + uuid.uuid4().hex
    other_id = rid + "-other"
    try:
        payload = {"id": rid, "title": "api_test", "pattern": r"hello\s+world", "priority": 50}
        response = client.post("/api/v1/rules/", headers=headers, json=payload)
        assert response.status_code == 200
        listing = client.get("/api/v1/rules/", headers=headers)
        assert listing.status_code == 200
        assert any(rule["id"] == rid for rule in listing.json()["rules"])

        preview = client.post("/api/v1/rules/preview", headers=headers, json={"text": "hello world"})
        assert preview.status_code == 200
        assert isinstance(preview.json(), dict)
        bad = client.put(f"/api/v1/rules/{rid}", headers=headers, json={"pattern": "("})
        assert bad.status_code == 400

        other = other_client.post("/api/v1/rules/", headers=other_headers,
                                  json={"id": other_id, "title": "tenant_only", "pattern": "tenant", "priority": 5})
        assert other.status_code == 200
        own_rules = client.get("/api/v1/rules/", headers=headers).json()["rules"]
        other_rules = other_client.get("/api/v1/rules/?tenant_id=rules-crud-other", headers=other_headers).json()["rules"]
        assert any(rule["id"] == other_id for rule in other_rules)
        assert not any(rule["id"] == other_id for rule in own_rules)
        assert client.delete(f"/api/v1/rules/{rid}", headers=headers).status_code == 200
    finally:
        store.delete_rule(rid)
        store.delete_rule(other_id)
