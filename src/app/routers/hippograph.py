"""Read-only hippograph intelligence endpoint.

Surfaces the entities RELATED to a seed (product / brand / user) by projecting the recent
decision-trace + conversion graph and recalling reward-weighted neighbours. READ-ONLY + role-gated:
it *proposes* related entities for dashboards/analysis — it never acts (any action would re-enter
policy → escalation → kill-switch → audit). The seed is canonicalized the SAME way nodes are, so it
matches the projected graph.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from src.app.models.db import get_db
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.platform.tenant_context import current_tenant_id

router = APIRouter(prefix="/api/v1/hippograph", tags=["hippograph"])


@router.get("/recall")
def hippograph_recall(
    seed: str = Query(..., description="entity reference: a SKU, brand name, or uid_hash"),
    kind: str = Query("product", description="product | brand | user"),
    top_k: int = Query(10, ge=1, le=50),
    limit: int = Query(2000, ge=1, le=20000, description="recent trace/conversion rows to project"),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    from src.app.services.entity_resolution import _brand_alias_map_for_profile, canonical_entity
    from src.app.services.hippograph import recall
    from src.app.services.hippograph_db import _DEFAULT_SKU_PATTERN, build_from_db

    tenant_id = current_tenant_id()
    graph = build_from_db(db, tenant_id=tenant_id, limit=limit)

    # Canonicalize the seed to a node id the SAME way build_from_db builds nodes.
    kw: Dict[str, Any] = {}
    k = str(kind or "product").strip().lower()
    if k == "brand":
        alias_map, known = _brand_alias_map_for_profile()
        kw = {"alias_map": alias_map, "known": known}
    elif k == "user":
        kw = {"already_hashed": True}
    elif k == "product":
        kw = {"sku_pattern": _DEFAULT_SKU_PATTERN}
    ref = canonical_entity(k, seed, **kw)
    seed_id = ref.id if ref else str(seed)

    items = recall(graph, [seed_id], top_k=top_k)
    out: List[Dict[str, Any]] = []
    for nid, score in items:
        node = graph.nodes.get(nid)
        out.append({
            "id": nid,
            "kind": node.kind if node else None,
            "label": node.label if node else nid,
            "score": round(float(score), 4),
            "reward_weight": round(float(node.weight), 2) if node else 0.0,
        })
    return {
        "seed": seed_id,
        "kind": k,
        "tenant_id": tenant_id,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "recall": out,
    }
