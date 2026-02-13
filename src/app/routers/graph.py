from typing import Dict, List
from fastapi import APIRouter, Query, HTTPException, Depends
from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
import json

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])


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
                where = []
                params = {"limit": limit}
                if since:
                    where.append("valid_from >= :since")
                    params["since"] = since
                if until:
                    where.append("valid_from <= :until")
                    params["until"] = until
                base = "SELECT id, agent_name, valid_from, input_data FROM decision_logs"
                if where:
                    base += " WHERE " + " AND ".join(where)
                base += " ORDER BY valid_from DESC LIMIT :limit"
                rows = db.execute(base, params).mappings().all()
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
                where = []
                params = {"limit": limit}
                if since:
                    where.append("event_time >= :since")
                    params["since"] = since
                if until:
                    where.append("event_time <= :until")
                    params["until"] = until
                base = "SELECT id, severity, path, event_time, details FROM security_events"
                if where:
                    base += " WHERE " + " AND ".join(where)
                base += " ORDER BY event_time DESC LIMIT :limit"
                rows = db.execute(base, params).mappings().all()
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
                rows = db.execute(
                    "SELECT id, event_id, title, severity FROM incidents ORDER BY created_at DESC LIMIT :limit",
                    {"limit": limit},
                ).mappings().all()
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
