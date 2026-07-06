"""Context-rot probes — session-carried constraints must not outlive an intent shift.

The live regression (trace 4f81a6c2): a gaming exploration left gpu_preference="with_discrete" in the
session's nqe_answered_fields; "clear my cart" cleared the cart, NOT the kv; the next "laptops for
work" turn carried the slot, the GPU hard-filter kept only discrete-GPU units, and the pool collapsed
48→1 (the one gaming laptop in budget) — so the office-vs-gaming conflict ranking (−12) never had a
choice. The guard drops a carried with_discrete slot when THIS turn's use-case says gpu_needed=False.
The control pins the boundary: no use-case shift → the carried slot is still honoured.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.utils import default_headers
from tests.test_recommend import _write_flags
from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.recommendations import RecommendationService

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
_FLAGS = {
    "USE_AGENT_CAPABILITIES": True,
    "AGENT_ROLLOUT_PERCENT": 100,
    "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
    "KILL_SWITCH": False,
    "DECISION_LOG_WRITES_ENABLED": False,
    "DEGRADATION": {"enabled": True},
    "TEST_FORCE_BAD_SKU": False,
}

client = TestClient(create_app(), headers=default_headers())

# One discrete-GPU gaming unit and one business laptop, both INSIDE the 1900-2100 band. A carried
# with_discrete slot keeps only CTX-GAME unless the use-case-shift guard drops it.
_CATALOG = [
    ("CTX-GAME", "Volt Gaming 16 FHD 144Hz RTX 4050 Laptop", 191900,
     '{"ram_gb": 16, "storage_gb": 512, "refresh_hz": 144, "gpu_discrete": true, "gpu": "RTX 4050"}'),
    ("CTX-BIZ", "Sable Business Pro 13 Laptop", 199900,
     '{"ram_gb": 16, "storage_gb": 512, "refresh_hz": 60, "gpu_discrete": false}'),
]


@pytest.fixture(scope="module", autouse=True)
def _seed():
    orig = RecommendationService.retrieve_candidates
    RecommendationService.retrieve_candidates = lambda self, query, limit=10: []
    _orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    _write_flags(_FLAGS)
    with db_session() as db:
        for sku, name, cents, specs in _CATALOG:
            db.execute(text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
                "VALUES (:id,:sku,:name,:c,'USD',:specs,1)"),
                {"id": sku, "sku": sku, "name": name, "c": cents, "specs": specs})
        db.commit()
    yield
    RecommendationService.retrieve_candidates = orig
    if _orig_flags is not None:
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            f.write(_orig_flags)


def _seed_carried_gpu_pref(uid: str) -> None:
    """Exactly what a prior gaming turn's NQE answers leave behind in session kv."""
    from src.app.deps import get_redis
    from src.app.services.memory import Memory
    Memory(get_redis()).set_kv(uid, {"nqe_answered_fields": {"gpu_preference": "with_discrete"}})


def _suggest(uid: str, query: str) -> dict:
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": query, "limit": 6})
    assert r.status_code == 200, r.text
    return r.json()


def test_carried_gpu_slot_does_not_hijack_a_work_query():
    """Turn N-1 (gaming) answered 'with a dedicated GPU'; turn N asks for WORK laptops. The carried
    slot must be dropped on the use-case shift (office_general: gpu_needed=False) so the business
    laptop survives the pool and a non-gaming unit ranks on top."""
    uid = f"ctxrot-{uuid4().hex[:8]}"
    _seed_carried_gpu_pref(uid)
    out = _suggest(uid, "i need help with laptops for work? budget is 1900 to 2100")
    results = out.get("results") or []
    assert results, f"no results: {str(out)[:300]}"
    cu = out.get("constraints_used") or {}
    # the guard's contract: the shift resolved office_general and the stale GPU slot is GONE
    assert cu.get("use_case") == "office_general", f"use_case did not resolve: {cu}"
    assert not cu.get("gpu_preference"), (
        f"stale gaming GPU slot survived the use-case shift: {cu.get('gpu_preference')}")
    # and the behavioral outcome: the pool is not gaming-only; a non-gaming unit ranks on top
    skus = [str(r.get("sku")) for r in results]
    assert "CTX-BIZ" in skus, (
        f"business laptop was hard-filtered out by the stale gaming GPU slot — pool: {skus}")
    assert "gaming" not in str(results[0].get("name") or "").lower(), (
        f"top pick is still a gaming unit for a work query: {results[0].get('name')}")


def test_carried_gpu_slot_holds_without_a_use_case_shift():
    """The guard's boundary: the same carried slot with NO use-case in the new query is still honoured
    (no shift → the buyer's earlier NQE answer stands). Asserted on the resolved-constraints contract —
    result composition varies with retrieval internals, the contract does not."""
    uid = f"ctxrot-{uuid4().hex[:8]}"
    _seed_carried_gpu_pref(uid)
    out = _suggest(uid, "laptop, budget 1900 to 2100")
    cu = out.get("constraints_used") or {}
    assert cu.get("gpu_preference") == "with_discrete", (
        f"carried GPU slot was dropped WITHOUT a use-case shift — it must hold: {cu}")
