"""Read-only hippograph intelligence endpoint.

Surfaces the entities RELATED to a seed (product / brand / user) by projecting the recent
decision-trace + conversion graph and recalling reward-weighted neighbours. READ-ONLY + role-gated:
it *proposes* related entities for dashboards/analysis — it never acts (any action would re-enter
policy → escalation → kill-switch → audit). The seed is canonicalized the SAME way nodes are, so it
matches the projected graph.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.models.db import get_db
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.platform.tenant_context import current_tenant_id

router = APIRouter(prefix="/api/v1/hippograph", tags=["hippograph"])


@router.get("/view")
def hippograph_view(
    seed_id: str = Query(..., min_length=1, max_length=300),
    purpose: str = Query(..., description="what_changed | historical_knowledge | supplier_fulfilment | product_fit | commercial_outcome"),
    case_id: str | None = Query(default=None, max_length=200),
    knowledge_cutoff: datetime | None = Query(default=None),
    evaluation_time: datetime | None = Query(default=None),
    max_depth: int = Query(4, ge=1, le=8),
    max_edges: int = Query(128, ge=1, le=512),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Select a bounded, bitemporal graph view without granting decision authority."""
    from src.app.services.hippograph_journey_store import (
        load_configuration_availability_edges,
        load_journey_edges,
    )
    from src.app.services.hippograph_view_selector import (
        MemoryQueryPurpose,
        select_graph_view,
        traverse_journey_view,
    )

    tenant_id = current_tenant_id()
    try:
        typed_purpose = MemoryQueryPurpose(purpose)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unsupported_graph_view_purpose") from exc
    edges = load_journey_edges(db, tenant_id=tenant_id, case_id=case_id)
    edges.extend(load_configuration_availability_edges(db, tenant_id=tenant_id))
    plan = select_graph_view(
        typed_purpose, max_depth=max_depth, max_edges=max_edges,
    )
    receipt = traverse_journey_view(
        edges, start_node_ids=(seed_id,), plan=plan,
        knowledge_cutoff=knowledge_cutoff, evaluation_time=evaluation_time,
    )
    return {
        "tenant_id": tenant_id,
        "case_id": case_id,
        "plan": plan.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "ranking_authority": "none",
        "commerce_authority": "none",
    }


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


@router.get("/journey")
def hippograph_journey(
    seed: str = Query(..., description="entity reference: shopping case, SKU, brand, or uid_hash"),
    kind: str = Query("shopping_case", description="shopping_case | product | brand | user"),
    top_k: int = Query(30, ge=1, le=100),
    limit: int = Query(2000, ge=1, le=20000),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Typed evidence journey; read-only and explicitly non-authoritative."""
    from src.app.services.entity_resolution import _brand_alias_map_for_profile, canonical_entity
    from src.app.services.hippograph_db import _DEFAULT_SKU_PATTERN, build_from_db
    from src.app.services.hippograph_journey_projection import project_hippograph_journey

    tenant_id = current_tenant_id()
    graph = build_from_db(db, tenant_id=tenant_id, limit=limit)
    normalized_kind = str(kind or "shopping_case").strip().lower()
    kwargs: Dict[str, Any] = {}
    if normalized_kind == "brand":
        alias_map, known = _brand_alias_map_for_profile()
        kwargs = {"alias_map": alias_map, "known": known}
    elif normalized_kind == "user":
        kwargs = {"already_hashed": True}
    elif normalized_kind == "product":
        kwargs = {"sku_pattern": _DEFAULT_SKU_PATTERN}
    ref = canonical_entity(normalized_kind, seed, **kwargs)
    seed_id = ref.id if ref else f"{normalized_kind}:{seed}"
    projection = project_hippograph_journey(graph, [seed_id], top_k=top_k)
    return {
        "tenant_id": tenant_id,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        **projection.model_dump(mode="json"),
    }
