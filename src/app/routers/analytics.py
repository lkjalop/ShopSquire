from __future__ import annotations

import json
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, Query

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.analytics.features_timeseries import security_timeseries
from src.app.analytics.risk_scoring import score_graph_risk
from src.app.services.db_read_routing import read_session
from src.app.services.dependency_resilience import call_with_resilience
from sqlalchemy import text


router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _load_security_events(limit: int = 200) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    def _query_rows():
        with read_session(read_class="analytics") as db:
            return db.execute(
                text("SELECT details FROM security_events ORDER BY event_time DESC LIMIT :limit"),
                {"limit": limit},
            ).fetchall()

    rows = call_with_resilience("db.analytics.security_events", _query_rows, timeout_s=4.0, retries=1)
    for (details,) in rows or []:
        try:
            blob = json.loads(details) if isinstance(details, str) else details
            analysis = blob.get("analysis") if isinstance(blob, dict) else {}
            events.append(analysis or {})
        except Exception:
            continue
    return events


@router.get("/fraud/timeseries")
def fraud_timeseries(
    days: int = Query(14, ge=1, le=90),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return call_with_resilience(
        "db.analytics.timeseries",
        lambda: _timeseries(days),
        timeout_s=5.0,
        retries=1,
    )


def _timeseries(days: int) -> Dict[str, Any]:
    with read_session(read_class="analytics") as db:
        return security_timeseries(db, days=days)


@router.get("/fraud/graph")
def fraud_graph(
    limit: int = Query(200, ge=10, le=1000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    events = _load_security_events(limit=limit)
    return score_graph_risk(events)


@router.post("/ragas/run_sampling")
def ragas_run_sampling(sample_rate: float = 0.1, limit: int = 200, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    try:
        from src.app.services.ragas_eval import run_sampling
        res = run_sampling(sample_rate=sample_rate, limit=limit)
        return {"ok": bool(res.get('ok')), "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/ragas/ci_guard")
def ragas_ci_guard(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    try:
        from src.app.services.ragas_eval import ci_guard_check
        res = ci_guard_check()
        return {"ok": bool(res.get('ok')), "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/ragas/summary")
def ragas_summary(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Return a human-friendly recent RAGAS quality summary for operators."""
    try:
        from src.app.services.ragas_eval import evaluation_summary
        def load_summary():
            with read_session(read_class="analytics") as db:
                return evaluation_summary(db)
        return {"ok": True, "summary": call_with_resilience(
            "db.analytics.ragas_summary", load_summary, timeout_s=4.0, retries=1)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/fraud/geo/top_asns")
def top_asns(
    limit: int = Query(200, ge=10, le=2000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    events = _load_security_events(limit=limit)
    counts: Dict[str, Dict[str, Any]] = {}
    for e in events:
        try:
            net = e.get("network") or {}
            geo = net.get("geo") or {}
            asn = str(geo.get("asn") or "0")
            org = geo.get("asn_org") or "unknown"
            risk = float(geo.get("risk", 0.0))
            rec = counts.setdefault(asn, {"asn": asn, "org": org, "count": 0, "avg_risk": 0.0})
            rec["count"] += 1
            rec["avg_risk"] = ((rec["avg_risk"] * (rec["count"] - 1)) + risk) / rec["count"]
        except Exception:
            continue
    top = sorted(counts.values(), key=lambda x: (x["avg_risk"], x["count"]), reverse=True)[:50]
    return {"top_asns": top}


@router.get("/fraud/geo/country_heatmap")
def country_heatmap(
    limit: int = Query(200, ge=10, le=2000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    events = _load_security_events(limit=limit)
    counts: Dict[str, int] = {}
    for e in events:
        try:
            net = e.get("network") or {}
            geo = net.get("geo") or {}
            cc = (geo.get("country") or "XX").upper()
            counts[cc] = counts.get(cc, 0) + 1
        except Exception:
            continue
    items = [{"country": k, "count": v} for (k, v) in counts.items()]
    items.sort(key=lambda x: x["count"], reverse=True)
    return {"countries": items}


@router.get("/fraud/geo/velocity_anomalies")
def velocity_anomalies(
    limit: int = Query(200, ge=10, le=2000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    events = _load_security_events(limit=limit)
    anoms = 0
    for e in events:
        try:
            net = e.get("network") or {}
            if bool(net.get("velocity_asn_anomaly")):
                anoms += 1
        except Exception:
            continue
    return {"velocity_anomalies": anoms}
