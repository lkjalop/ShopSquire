"""DB-backed hippograph projection (agnostic CORE, read-only).

Queries the recent decision_trace_events (source→target edges) + conversion_event (reward edges) and
projects them through services/hippograph.project_graph, canonicalizing nodes with the active
StoreProfile's brand aliases. READ-ONLY + best-effort: any query error degrades to an empty/partial
graph (it informs agents, never blocks them). SKUs are matched permissively (space-free tokens) so
trace/conversion product ids stay canonical without a catalog round-trip.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text

from src.app.services.entity_resolution import _brand_alias_map_for_profile
from src.app.services.hippograph import HippoGraph, project_graph

# A SKU node id is a single space-free token (GAM-0002, ATTR-1, ...); product *names* (with spaces)
# fall through to a `name:` node and never collide with a real SKU.
_DEFAULT_SKU_PATTERN = r"[A-Za-z0-9][\w.\-]{0,63}"


def _maybe_project_findings(db, graph: HippoGraph, *, tenant_id: str, limit: int, sku_pattern: str, anomaly_fn) -> HippoGraph:
    try:
        from src.app.services.hippograph import project_findings
        from src.app.services.market_analysis import load_recent_findings, run_analysis
        # Read PERSISTED findings (fast — the batch computes them); only fall back to inline analysis
        # when an anomaly_fn is injected (tests) or no findings have been persisted yet.
        findings = load_recent_findings(db, limit=200, tenant_id=tenant_id)
        if not findings or anomaly_fn is not None:
            findings = run_analysis(db, limit=limit, anomaly_fn=anomaly_fn, tenant_id=tenant_id)
        return project_findings(graph, findings, sku_pattern=sku_pattern)
    except Exception:
        return graph  # findings are additive — degrade to the base graph, never break it


def _maybe_project_human_feedback(db, graph: HippoGraph, *, tenant_id: str, limit: int, sku_pattern: str) -> HippoGraph:
    try:
        from src.app.services.hippograph import project_human_feedback
        from src.app.services.human_feedback import load_recent
        rows = load_recent(db, limit=limit, tenant_id=tenant_id)
        return project_human_feedback(graph, rows, sku_pattern=sku_pattern) if rows else graph
    except Exception:
        return graph  # feedback is additive — degrade to the base graph, never break it


def _maybe_project_catalog(db, graph: HippoGraph, *, tenant_id: str, alias_map, known, limit: int = 500) -> HippoGraph:
    """Cold-start seeding (Track B, 2026-07-09): active-catalog product↔brand edges at LOW weight
    so a history-less SKU is reachable (live diagnosis: current-catalog seeds had zero graph
    presence). Additive; degrades to the base graph on any error."""
    try:
        from src.app.services.hippograph import project_catalog
        rows = db.execute(
            text("SELECT DISTINCT p.sku, p.name FROM products p "
                 "JOIN product_classification pc ON pc.sku=p.sku "
                 "WHERE p.active = 1 AND pc.tenant_id=:tenant ORDER BY p.id DESC LIMIT :lim"),
            {"tenant": tenant_id, "lim": int(limit)},
        ).fetchall()
        return project_catalog(graph, [{"sku": r[0], "name": r[1]} for r in rows],
                               alias_map=alias_map, known=known)
    except Exception:
        return graph


def build_from_db(
    db,
    *,
    tenant_id: str,
    limit: int = 2000,
    profile_id: Optional[str] = None,
    sku_pattern: str = _DEFAULT_SKU_PATTERN,
    include_findings: bool = False,
    include_human_feedback: bool = False,
    include_catalog: bool = False,
    anomaly_fn=None,
) -> HippoGraph:
    """Project the most recent ``limit`` trace + conversion rows into an in-memory hippograph. Set
    ``include_findings`` to also project M3 findings as ``finding`` nodes; ``include_human_feedback``
    to fold in human-in-the-loop signals (approvals/rejections/returns/...) as signed recall priors."""
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required for Hippograph projection")
    if db is None:
        return HippoGraph()
    alias_map, known = _brand_alias_map_for_profile(profile_id)

    trace_rows = []
    try:
        rows = db.execute(
            text(
                "SELECT source_type, source_id, target_type, target_id, event_type "
                "FROM decision_trace_events WHERE COALESCE(tenant_id,'default')=:tenant "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"tenant": tenant, "lim": int(limit)},
        ).fetchall()
        trace_rows = [
            {"source_type": r[0], "source_id": r[1], "target_type": r[2], "target_id": r[3],
             "event_type": r[4]}
            for r in rows
        ]
    except Exception:
        trace_rows = []  # table absent / query error → degrade, never raise

    conv_rows = []
    try:
        crows = db.execute(
            text(
                "SELECT decision_id, attributed_skus_json, value_cents "
                "FROM conversion_event WHERE COALESCE(tenant_id,'default')=:tenant "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"tenant": tenant, "lim": int(limit)},
        ).fetchall()
        for r in crows:
            try:
                skus = json.loads(r[1]) if r[1] else []
            except Exception:
                skus = []
            conv_rows.append(
                {
                    "decision_id": r[0],
                    "attributed_skus": skus if isinstance(skus, list) else [],
                    "value_cents": r[2],
                }
            )
    except Exception:
        conv_rows = []

    graph = project_graph(
        trace_rows, conv_rows, alias_map=alias_map, known=known, sku_pattern=sku_pattern
    )
    if include_findings:
        graph = _maybe_project_findings(db, graph, tenant_id=tenant, limit=limit,
                                        sku_pattern=sku_pattern, anomaly_fn=anomaly_fn)
    if include_human_feedback:
        graph = _maybe_project_human_feedback(db, graph, tenant_id=tenant, limit=limit, sku_pattern=sku_pattern)
    if include_catalog:
        graph = _maybe_project_catalog(db, graph, tenant_id=tenant, alias_map=alias_map, known=known)
    return graph
