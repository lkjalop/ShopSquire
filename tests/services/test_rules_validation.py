def test_rules_reject_invalid_regex(owned_operator_client):
    client, headers = owned_operator_client("rules-validation", role="developer")

    r = client.post("/api/v1/rules/", headers=headers, json={"title": "bad", "pattern": "("})
    assert r.status_code == 400
    body = r.json()
    assert body.get("detail", {}).get("error") == "invalid_regex"


def test_rules_dry_run_priority_order(owned_operator_client):
    client, headers = owned_operator_client("rules-validation", role="developer")

    payload = {
        "text": "please refund my order",
        "rules": [
            {"id": "r2", "title": "product_search", "pattern": r"\bshow\s+me\b", "priority": 50},
            {"id": "r1", "title": "return_request", "pattern": r"\brefund\b", "priority": 10},
        ],
    }
    r = client.post("/api/v1/rules/dry-run", headers=headers, json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["match"]["id"] == "r1"
