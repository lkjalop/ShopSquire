from __future__ import annotations

"""RL traces exporter: combines decision_logs, decision_trace_events, and reward_signal.

Writes JSONL to analytics/rl_traces/traces.jsonl with entries of the form:
{
  "trace_id": str,
  "state": {input_data, retrieved_context},
  "action": proposed_action,
  "policy": {policy_version, policy_gate},
  "reward": float,
  "timestamps": {valid_from, system_from}
}
"""

import json
import os
from typing import Any, Dict, List

from sqlalchemy import text
from src.app.models.db import db_session


def _ensure_outdir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def export_rl_traces(output_path: str = "analytics/rl_traces/traces.jsonl") -> str:
    _ensure_outdir(output_path)
    rows: List[Dict[str, Any]] = []
    rewards_by_trace: Dict[str, float] = {}
    try:
        with db_session() as db:
            # Gather reward_signal events
            try:
                ev = db.execute(
                    text(
                        "SELECT trace_id, payload, created_at FROM decision_trace_events WHERE event_type='reward_signal'"
                    )
                ).fetchall()
                for r in ev or []:
                    tid = str(r[0])
                    payload = {}
                    try:
                        payload = json.loads(r[1]) if r[1] else {}
                    except Exception:
                        payload = {}
                    rewards_by_trace[tid] = float(payload.get("reward") or 0.0)
            except Exception:
                rewards_by_trace = {}

            # Join decision_logs (proposed actions) to reward via trace_id if present in input_data/proposed_action
            try:
                logs = db.execute(text("SELECT id, valid_from, system_from, input_data, retrieved_context, proposed_action, policy_version, approval_required, execution_status FROM decision_logs")).fetchall()
            except Exception:
                logs = []
            for row in logs or []:
                dec_id = str(row[0])
                valid_from = str(row[1] or "")
                system_from = str(row[2] or "")
                try:
                    input_data = json.loads(row[3] or "{}")
                except Exception:
                    input_data = {}
                try:
                    retrieved_context = json.loads(row[4] or "{}")
                except Exception:
                    retrieved_context = {}
                try:
                    proposed_action = json.loads(row[5] or "{}")
                except Exception:
                    proposed_action = {}
                policy_version = str(row[6] or "v1")
                # Attempt to discover trace_id from proposed_action or input_data
                trace_id = None
                for container in (proposed_action, input_data):
                    if isinstance(container, dict):
                        tid = container.get("trace_id") or container.get("proposal", {}).get("trace_id")
                        if tid:
                            trace_id = str(tid)
                            break
                reward = rewards_by_trace.get(trace_id or dec_id, 0.0)
                rows.append({
                    "trace_id": trace_id or dec_id,
                    "state": {"input_data": input_data, "retrieved_context": retrieved_context},
                    "action": proposed_action,
                    "policy": {"policy_version": policy_version},
                    "reward": reward,
                    "timestamps": {"valid_from": valid_from, "system_from": system_from},
                })
    except Exception:
        rows = []

    # Write JSONL
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return output_path


if __name__ == "__main__":
    out = export_rl_traces()
    print(json.dumps({"status": "ok", "output": out}))
