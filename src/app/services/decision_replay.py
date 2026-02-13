from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.policy_gate import PolicyGate


def _json_obj(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
            if isinstance(out, dict):
                return out
        except Exception:
            return {}
    return {}


def replay_decision(decision_id: str) -> Dict[str, Any]:
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT id, agent_name, input_data, retrieved_context, proposed_action, policy_version, execution_status, valid_from
                FROM decision_logs
                WHERE id = :id
                ORDER BY valid_from DESC
                LIMIT 1
                """
            ),
            {"id": decision_id},
        ).fetchone()
    if not row:
        return {"available": False, "decision_id": decision_id}
    input_data = _json_obj(row[2])
    retrieved_context = _json_obj(row[3])
    proposed_action = _json_obj(row[4])
    old_status = str(row[6] or "unknown")
    gate = PolicyGate(flags={})
    current_gate = {}
    try:
        current_gate = gate.evaluate({"proposal": proposed_action}, context={"retrieved_context": retrieved_context, "input_data": input_data}) or {}
    except Exception:
        current_gate = {}
    drift = {
        "old_execution_status": old_status,
        "new_policy_verdict": current_gate.get("verdict"),
        "changed": bool(current_gate),
    }
    return {
        "available": True,
        "decision_id": decision_id,
        "agent_name": row[1],
        "valid_from": row[7],
        "replay": {
            "input_data": input_data,
            "retrieved_context": retrieved_context,
            "proposed_action": proposed_action,
            "current_policy": current_gate,
        },
        "drift": drift,
    }


def build_causal_graph(trace_id: str) -> Dict[str, Any]:
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, event_type, source_type, source_id, target_type, target_id, payload, created_at
                FROM decision_trace_events
                WHERE trace_id = :tid
                ORDER BY created_at ASC
                """
            ),
            {"tid": trace_id},
        ).fetchall()
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    last_event_id = None
    for r in rows or []:
        event_id = str(r[0])
        payload = _json_obj(r[6])
        nodes.append(
            {
                "id": event_id,
                "event_type": r[1],
                "source_type": r[2],
                "source_id": r[3],
                "target_type": r[4],
                "target_id": r[5],
                "created_at": r[7],
            }
        )
        parent = payload.get("causal_parent_event_id") if isinstance(payload, dict) else None
        if parent:
            edges.append({"from": str(parent), "to": event_id, "type": "causal_parent"})
        elif last_event_id:
            edges.append({"from": last_event_id, "to": event_id, "type": "temporal"})
        last_event_id = event_id
    return {"trace_id": trace_id, "nodes": nodes, "edges": edges}
