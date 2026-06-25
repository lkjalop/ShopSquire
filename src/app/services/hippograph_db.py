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


def build_from_db(
    db,
    *,
    limit: int = 2000,
    profile_id: Optional[str] = None,
    sku_pattern: str = _DEFAULT_SKU_PATTERN,
) -> HippoGraph:
    """Project the most recent ``limit`` trace + conversion rows into an in-memory hippograph."""
    if db is None:
        return HippoGraph()
    alias_map, known = _brand_alias_map_for_profile(profile_id)

    trace_rows = []
    try:
        rows = db.execute(
            text(
                "SELECT source_type, source_id, target_type, target_id "
                "FROM decision_trace_events ORDER BY created_at DESC LIMIT :lim"
            ),
            {"lim": int(limit)},
        ).fetchall()
        trace_rows = [
            {"source_type": r[0], "source_id": r[1], "target_type": r[2], "target_id": r[3]}
            for r in rows
        ]
    except Exception:
        trace_rows = []  # table absent / query error → degrade, never raise

    conv_rows = []
    try:
        crows = db.execute(
            text(
                "SELECT decision_id, attributed_skus_json, value_cents "
                "FROM conversion_event ORDER BY created_at DESC LIMIT :lim"
            ),
            {"lim": int(limit)},
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

    return project_graph(
        trace_rows, conv_rows, alias_map=alias_map, known=known, sku_pattern=sku_pattern
    )
