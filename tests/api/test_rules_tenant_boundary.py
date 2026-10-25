import uuid

import pytest

from src.app.routers.rules import store


@pytest.fixture
def rules_actor(owned_operator_client):
    client, headers = owned_operator_client("rules-owned", role="developer")
    identifier = "rule-boundary-" + uuid.uuid4().hex
    foreign = identifier + "-foreign"
    shared = identifier + "-global"
    for rule_id, tenant in [(foreign, "rules-foreign"), (shared, None)]:
        assert store.create_rule({"id": rule_id, "tenant_id": tenant,
                                  "title": identifier, "pattern": "private", "active": True})
    try:
        yield client, headers, foreign, shared
    finally:
        for rule_id in [foreign, shared, identifier]:
            store.delete_rule(rule_id)


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/?tenant_id=rules-foreign", None),
    ("post", "/", {"title": "foreign", "tenant_id": "rules-foreign"}),
    ("post", "/preview", {"text": "private", "tenant_id": "rules-foreign"}),
    ("post", "/dry-run", {"text": "private", "tenant_id": "rules-foreign"}),
])
def test_rules_reject_foreign_requested_scope(rules_actor, method, path, payload):
    client, headers, _, _ = rules_actor
    response = client.request(method, "/api/v1/rules" + path, headers=headers, json=payload)
    assert response.status_code == 403


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_rules_cannot_read_or_mutate_foreign_identifier(rules_actor, method):
    client, headers, foreign, _ = rules_actor
    response = client.request(method, "/api/v1/rules/" + foreign,
                              headers=headers, json={"title": "changed"} if method == "put" else None)
    assert response.status_code == 404
    assert store.get_rule(foreign)["title"] != "changed"


@pytest.mark.parametrize("method", ["put", "delete"])
def test_tenant_operator_cannot_mutate_global_rule(rules_actor, method):
    client, headers, _, shared = rules_actor
    response = client.request(method, "/api/v1/rules/" + shared, headers=headers,
                              json={"title": "changed"} if method == "put" else None)
    assert response.status_code == 404
    assert store.get_rule(shared)["title"] != "changed"


def test_owned_rule_crud_inherits_scope_and_lists_shared_rules(rules_actor):
    client, headers, foreign, shared = rules_actor
    own = foreign.removesuffix("-foreign")
    root = "/api/v1/rules/"
    response = client.post(root, headers=headers, json={"id": own, "title": "mine", "pattern": "owned"})
    assert response.status_code == 200
    assert store.get_rule(own)["tenant_id"] == headers["x-tenant-id"]
    listing = client.get(root, headers=headers).json()["rules"]
    assert own in [rule["id"] for rule in listing]
    assert shared in [rule["id"] for rule in listing]
    assert foreign not in [rule["id"] for rule in listing]
    assert client.get(root + own, headers=headers).status_code == 200
    assert client.put(root + own, headers=headers, json={"title": "revised"}).status_code == 200
    assert store.get_rule(own)["title"] == "revised"
    assert client.delete(root + own, headers=headers).status_code == 200
    assert store.get_rule(own) is None


@pytest.mark.parametrize("operation", ["get", "update", "delete"])
def test_store_scope_is_enforced_in_database_predicate(rules_actor, operation):
    _, headers, foreign, _ = rules_actor
    tenant = headers["x-tenant-id"]
    if operation == "get":
        assert store.get_rule(foreign, tenant_id=tenant) is None
    elif operation == "update":
        assert store.update_rule(foreign, {"title": "changed"}, tenant_id=tenant) is False
    else:
        assert store.delete_rule(foreign, tenant_id=tenant) is False
    assert store.get_rule(foreign)["title"] != "changed"
