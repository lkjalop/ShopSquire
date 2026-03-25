from typing import Dict, List
from fastapi import APIRouter, Query, HTTPException, Depends
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from sqlalchemy import text
import json

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])

_GRAPH_DECISIONS_SQL = text(
        """
        SELECT id, agent_name, valid_from, input_data
        FROM decision_logs
        WHERE (:since IS NULL OR valid_from >= :since)
            AND (:until IS NULL OR valid_from <= :until)
        ORDER BY valid_from DESC
        LIMIT :limit
        """
)

_GRAPH_SECURITY_SQL = text(
        """
        SELECT id, severity, path, event_time, details
        FROM security_events
        WHERE (:since IS NULL OR event_time >= :since)
            AND (:until IS NULL OR event_time <= :until)
        ORDER BY event_time DESC
        LIMIT :limit
        """
)

_GRAPH_INCIDENTS_SQL = text(
        """
        SELECT id, event_id, title, severity
        FROM incidents
        ORDER BY created_at DESC
        LIMIT :limit
        """
)


@router.get("/context")
def context_graph(
    uid: str | None = Query(None),
    since: str | None = Query(None, description="ISO timestamp lower bound"),
    until: str | None = Query(None, description="ISO timestamp upper bound"),
    limit: int = Query(50, ge=1, le=500),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Export a lightweight context graph of recent decisions, security events, incidents.

    Nodes: {id, type, label}
    Edges: {source, target, relation}
    """
    nodes: List[Dict] = []
    edges: List[Dict] = []
    try:
        with db_session() as db:
            # Decisions
            try:
                params = {"limit": limit, "since": since, "until": until}
                rows = db.execute(_GRAPH_DECISIONS_SQL, params).mappings().all()
                for r in rows:
                    label = f"decision:{r.get('agent_name')}"
                    nodes.append({"id": r.get("id"), "type": "decision", "label": label})
                    # Attempt to extract uid or sku from input_data for relational edges
                    try:
                        inp = r.get("input_data") or {}
                        if isinstance(inp, str):
                            inp = json.loads(inp)
                        sku = inp.get("proposal", {}).get("sku") if isinstance(inp, dict) else None
                        # Filter by uid when provided (best-effort, check a few common fields)
                        if uid:
                            maybe_uid = inp.get("uid") or inp.get("user_id") or inp.get("customer_id")
                            if maybe_uid and str(maybe_uid) != str(uid):
                                # skip nodes not matching uid filter
                                continue
                        if sku:
                            nodes.append({"id": sku, "type": "product", "label": f"product:{sku}"})
                            edges.append({"source": r.get("id"), "target": sku, "relation": "proposed_for"})
                    except Exception:
                        pass
            except Exception:
                pass
            # Security events
            try:
                params = {"limit": limit, "since": since, "until": until}
                rows = db.execute(_GRAPH_SECURITY_SQL, params).mappings().all()
                for r in rows:
                    label = f"security:{r.get('severity')}:{r.get('path')}"
                    # If uid filter present, attempt to match against event details payload
                    if uid:
                        try:
                            det = r.get("details")
                            det = json.loads(det) if isinstance(det, str) else det
                            payload = det.get("payload") if isinstance(det, dict) else None
                            maybe_uid = None
                            if isinstance(payload, dict):
                                maybe_uid = payload.get("uid") or payload.get("user_id") or payload.get("customer_id")
                            if maybe_uid and str(maybe_uid) != str(uid):
                                continue
                        except Exception:
                            pass
                    nodes.append({"id": r.get("id"), "type": "security_event", "label": label})
            except Exception:
                pass
            # Incidents
            try:
                rows = db.execute(_GRAPH_INCIDENTS_SQL, {"limit": limit}).mappings().all()
                for r in rows:
                    nodes.append({"id": r.get("id"), "type": "incident", "label": f"incident:{r.get('severity')}:{r.get('title')}"})
                    if r.get("event_id"):
                        edges.append({"source": r.get("event_id"), "target": r.get("id"), "relation": "escalated_to"})
            except Exception:
                pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # Deduplicate nodes by id
    seen = set()
    unique_nodes: List[Dict] = []
    for n in nodes:
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        unique_nodes.append(n)
    return {"nodes": unique_nodes, "edges": edges}


@router.get("/fraud-rings/dashboard")
def fraud_rings_dashboard(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    min_ring_size: int = Query(2, ge=2, le=100, description="Minimum accounts in a ring to surface"),
    limit: int = Query(20, ge=1, le=200, description="Max rings to return"),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Dashboard-grade fraud-ring summary across all accounts.

    Queries decision_logs for fraud scoring results and groups accounts by shared
    signals (IP, device, address) to surface probable ring structures.

    Falls back gracefully when the GNN service is unavailable.
    """
    summary: Dict = {
        "window_days": days,
        "min_ring_size": min_ring_size,
        "rings": [],
        "total_rings_detected": 0,
        "high_risk_accounts": [],
        "method": "db_heuristic",
    }
    try:
        with db_session() as db:
            # Pull recent fraud score decisions
            try:
                rows = db.execute(
                    text(
                        """
                        SELECT id, agent_name, valid_from, input_data
                        FROM decision_logs
                        WHERE agent_name LIKE '%fraud%'
                          AND valid_from >= NOW() - :days * INTERVAL '1 day'
                        ORDER BY valid_from DESC
                        LIMIT 2000
                        """
                    ),
                    {"days": days},
                ).mappings().all()
            except Exception:
                rows = []

            # Group by shared signals extracted from input_data
            ip_to_accounts: Dict[str, List[str]] = {}
            device_to_accounts: Dict[str, List[str]] = {}
            account_scores: Dict[str, float] = {}

            for r in rows:
                try:
                    inp = r.get("input_data") or {}
                    if isinstance(inp, str):
                        inp = json.loads(inp)
                    acct = str(inp.get("account_id") or inp.get("uid") or inp.get("user_id") or "").strip()
                    if not acct:
                        continue
                    score = float(inp.get("fraud_score") or inp.get("score") or 0.0)
                    account_scores[acct] = max(account_scores.get(acct, 0.0), score)
                    ip = str(inp.get("ip") or inp.get("remote_ip") or "")
                    if ip:
                        ip_to_accounts.setdefault(ip, [])
                        if acct not in ip_to_accounts[ip]:
                            ip_to_accounts[ip].append(acct)
                    dev = str(inp.get("device_id") or inp.get("fingerprint") or "")
                    if dev:
                        device_to_accounts.setdefault(dev, [])
                        if acct not in device_to_accounts[dev]:
                            device_to_accounts[dev].append(acct)
                except Exception:
                    continue

            # Build ring candidates from shared signals
            ring_map: Dict[str, set] = {}
            for signal_val, accounts in {**ip_to_accounts, **device_to_accounts}.items():
                if len(accounts) >= min_ring_size:
                    ring_key = "|".join(sorted(accounts))
                    ring_map.setdefault(ring_key, set()).update(accounts)

            rings = []
            for key, members in ring_map.items():
                if len(members) < min_ring_size:
                    continue
                avg_score = round(
                    sum(account_scores.get(a, 0.0) for a in members) / max(1, len(members)), 4
                )
                rings.append({
                    "size": len(members),
                    "accounts": sorted(members)[:20],
                    "avg_fraud_score": avg_score,
                    "risk": "high" if avg_score >= 70 else ("medium" if avg_score >= 40 else "low"),
                })
            rings.sort(key=lambda x: (-x["avg_fraud_score"], -x["size"]))
            rings = rings[:limit]

            summary["rings"] = rings
            summary["total_rings_detected"] = len(rings)
            summary["high_risk_accounts"] = sorted(
                [{"account_id": a, "score": s} for a, s in account_scores.items() if s >= 70],
                key=lambda x: -x["score"],
            )[:20]
    except Exception as exc:
        summary["error"] = str(exc)[:200]

    # Attempt GNN enrichment for top rings (best-effort)
    try:
        from src.app.services.gnn_fraud_detector import predict_fraud_risk
        summary["method"] = "db_heuristic+gnn"
        for ring in summary["rings"][:5]:
            for acct in ring.get("accounts", [])[:3]:
                try:
                    pred = predict_fraud_risk(acct)
                    if getattr(pred, "ring_detected", False):
                        ring["gnn_confirmed"] = True
                        break
                except Exception:
                    pass
    except Exception:
        pass

    return summary


@router.get("/fraud-rings")
def fraud_rings(
    account_id: str = Query(..., min_length=1),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Return the current fraud-ring view for an account using graph + GNN heuristics."""
    try:
        from src.app.services.gnn_fraud_detector import extract_subgraph_features, predict_fraud_risk
        from src.app.services.graph_retrieval import get_graph_adapter
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"fraud_graph_unavailable:{exc}")

    features = extract_subgraph_features(account_id)
    prediction = predict_fraud_risk(account_id)
    related = []
    try:
        adapter = get_graph_adapter()
        related = adapter.related_entities(node_type="account", node_id=account_id, limit=25) or []
    except Exception:
        related = []
    return {
        "account_id": account_id,
        "gnn_score": round(float(getattr(prediction, "gnn_score", 0.0) or 0.0), 4),
        "ring_detected": bool(getattr(prediction, "ring_detected", False)),
        "method": str(getattr(prediction, "method", "unknown")),
        "explanation": str(getattr(prediction, "explanation", ""))[:500],
        "features": {
            "degree": int(features.degree),
            "shared_address_count": int(features.shared_address_count),
            "shared_device_count": int(features.shared_device_count),
            "shared_ip_count": int(features.shared_ip_count),
            "transaction_velocity_24h": float(features.transaction_velocity_24h),
            "avg_neighbor_degree": float(features.avg_neighbor_degree),
            "max_ring_size": int(features.max_ring_size),
            "account_age_days": float(features.account_age_days),
            "chargeback_rate": float(features.chargeback_rate),
        },
        "related_entities": related[:25],
    }
