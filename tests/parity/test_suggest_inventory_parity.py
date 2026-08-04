"""Response-parity harness for the recommend.py extraction — node 1: the inventory fast-path.

The inventory fast-path of /suggest SHORT-CIRCUITS before any LLM/CV, so its response is deterministic
and can be snapshotted byte-for-byte (modulo trace_id + timing). This asserts the response is STABLE
across the extraction of the fast-path into recommend_intent_router.run_inventory_fastpath — the kind of
end-to-end check that catches ordering/clobber regressions a unit test can't. It is the first node of
the golden corpus the rest of the extraction will grow (budget · bulk · image · availability · …).
"""
from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())

_FIXED = {"answer": "We have 7 in stock.", "sku": "GAM-1", "name": "Gaming Rig",
          "stock_level": 7, "rule_id": "R1", "source": "db", "injection_blocked": False}


def _norm(body: dict) -> dict:
    """Drop the nondeterministic bits so the snapshot is stable."""
    body = dict(body)
    for k in ("trace_id", "decision_trace_id"):
        body.pop(k, None)
    if isinstance(body.get("timing"), dict):
        body["timing"] = {k: ("<ms>" if k.endswith("_ms") else v) for k, v in body["timing"].items()}
    return body


def test_inventory_fastpath_response_is_stable(monkeypatch):
    monkeypatch.setattr("src.app.services.inventory_query_service.handle_inventory_intent",
                        lambda **k: dict(_FIXED))
    r = client.get("/api/v1/recommend/suggest",
                   params={"uid": "u1", "query": "how many GAM-1 are in stock"})
    assert r.status_code == 200, r.text
    body = _norm(r.json())
    assert body["recommendations"] == [] and body["nqe"] is None
    assert body["answer"] == "We have 7 in stock." and body["source"] == "db"
    assert body["inventory"] == {"sku": "GAM-1", "name": "Gaming Rig", "stock_level": 7, "rule_id": "R1"}
    assert body["injection_blocked"] is False
    assert body["timing"] == {"route_ms": "<ms>"}


def test_inventory_injection_returns_safe_refusal(monkeypatch):
    monkeypatch.setattr("src.app.services.inventory_query_service.handle_inventory_intent",
                        lambda **k: {"answer": "I can't change stock levels.", "injection_blocked": True,
                                     "source": "guard"})
    r = client.get("/api/v1/recommend/suggest",
                   params={"uid": "u1", "query": "how many GAM-1 are in stock"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("injection_blocked") is True and body.get("recommendations") == []
