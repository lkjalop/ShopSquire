"""Phase 1.5 #1 — retrieval must span the device host UNION for a capability query.

Root cause of the replay's gpu_vram_gb/ram_gb 'failures': a query routing to el-6-6 (Laptops) with a
capability requirement retrieved ONLY that leaf, so a qualifying high-VRAM machine classified under
el-6-11-2 (Gaming Laptops) was never a candidate — closest-match then faithfully showed FAILING
laptops. The capability FLOOR already spanned the union; retrieval now does too. This pins it:
constructs the decision directly (no model router) so the retrieval scope is tested deterministically.

Skips if the demo catalog / host-union sibling products aren't present.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _db_or_skip():
    # the DEMO catalog explicitly (conftest overrides DATABASE_URL to a bare test DB) — this is a
    # characterization gate that runs when the demo catalog is present, like the off-catalog gate.
    url = os.getenv("SHOPSQUIRE_DEMO_DB") or "sqlite:///C:/AI/ShopSquire/tmp/demo.sqlite"
    try:
        db = sessionmaker(bind=create_engine(url))()
        # the sibling-node high-VRAM laptops the fix must surface
        n = db.execute(text("SELECT COUNT(*) FROM products WHERE sku IN ('LAP-858DC749','LAP-BCBAFE20')")).scalar()
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"no demo catalog: {exc}")
    if not n:
        pytest.skip("demo catalog lacks the host-union sibling products")
    return db


def test_capability_query_retrieval_spans_host_union():
    from src.app.services.recommendation_core.core import _exec_retrieve
    from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope
    from src.app.services.recommendation_core.turn_router import TurnDecision

    db = _db_or_skip()
    try:
        env = TurnEnvelope.from_suggest_params(
            query="a laptop with a 16GB VRAM discrete GPU", uid="t", tenant_id="default", budget_max=6000)
        # route to el-6-6 (plain Laptops) with a high-VRAM requirement — the exact leaf-only case.
        decision = TurnDecision(
            lane="SEARCH", node_handle="el-6-6",
            node_path="Electronics > Computers > Laptops",
            requirements={"gpu_vram_gb": [(">=", 16.0)]},
        )
        resp = CoreResponse(envelope=env, lane="SEARCH")
        _exec_retrieve(db, env, decision, resp, limit=10)
    finally:
        db.close()

    mode = str((resp.extras.get("evidence") or {}).get("retrieval_mode") or "")
    assert "el-6-11-2" in mode, f"retrieval did not span the Gaming-Laptops host node: {mode!r}"
    shown = {p.sku for p in resp.products}
    # a qualifying sibling-node laptop (Legion Pro 7 24GB / OMEN 16GB) must now be a candidate,
    # and — meeting the requirement — must rank at/near the top (fit-group is the top sort stage).
    assert shown & {"LAP-858DC749", "LAP-BCBAFE20"}, "qualifying host-union laptop still not retrieved"
    top = resp.products[0]
    assert (top.fit or {}).get("overall") == "meets", "a meeting product should lead once retrieved"
