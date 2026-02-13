from __future__ import annotations

"""Simple windowed drift computation for query clusters.

Computes ratio of change in cluster sizes across two windows.
"""

from typing import List, Dict, Any
from collections import defaultdict
from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.observability.metrics import record_query_cluster_drift


def _load_clusters(window_minutes: int) -> List[Dict[str, Any]]:
    with db_session() as db:
        try:
            rows = db.execute(
                sql_text(
                    """
                    SELECT id, label, size, created_at
                    FROM query_clusters
                    WHERE created_at >= datetime('now', '-' || :mins || ' minutes')
                    ORDER BY created_at DESC
                    """
                ),
                {"mins": int(window_minutes)},
            ).fetchall()
            items: List[Dict[str, Any]] = []
            for r in rows:
                items.append({"id": r[0], "label": r[1], "size": int(r[2] or 0), "created_at": r[3]})
            return items
        except Exception:
            return []


def compute_drift(window_a_min: int, window_b_min: int, model: str | None = None) -> Dict[str, Any]:
    a = _load_clusters(window_a_min)
    b = _load_clusters(window_b_min)

    agg_a = defaultdict(int)
    agg_b = defaultdict(int)
    for it in a:
        agg_a[it.get("label") or "unknown"] += int(it.get("size") or 0)
    for it in b:
        agg_b[it.get("label") or "unknown"] += int(it.get("size") or 0)

    results: List[Dict[str, Any]] = []
    labels = set(list(agg_a.keys()) + list(agg_b.keys()))
    for lab in labels:
        va = float(agg_a.get(lab, 0))
        vb = float(agg_b.get(lab, 0))
        denom = max(va, 1.0)
        ratio = (vb - va) / denom
        results.append({"cluster": lab, "ratio": ratio, "window_a_min": window_a_min, "window_b_min": window_b_min})
        try:
            record_query_cluster_drift(lab, model or "query_clusterer", ratio, window_label=f"{window_a_min}->{window_b_min}")
        except Exception:
            pass
    return {"drift": results, "model": model or "query_clusterer"}