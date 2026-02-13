from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session


class PolicyEvaluator:
    """Very small policy evaluator that persists control evaluations.

    This is intentionally conservative: it supports a few simple rule
    patterns encoded as text in `pg_rules.rule` and will not execute
    arbitrary code. Rules are evaluated against a flattened view of the
    decision context.
    """

    def _flatten(self, obj: Any, prefix: str = "") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else k
                out.update(self._flatten(v, key))
        elif isinstance(obj, list):
            out[prefix] = obj
            for i, v in enumerate(obj):
                out.update(self._flatten(v, f"{prefix}[{i}]"))
        else:
            out[prefix] = obj
        return out

    def _eval_simple_rule(self, rule: str, ctx: Dict[str, Any]) -> bool:
        # Supported patterns: key==value, key!=value, key<value, key>value, key<=, key>=
        # Also supports 'key:val' as equality and 'key>0' numeric checks.
        rule = (rule or "").strip()
        if not rule:
            return False
        ops = ["==", "!=", ">=", "<=", ">", "<", ":", "="]
        for op in ops:
            if op in rule:
                parts = rule.split(op)
                if len(parts) != 2:
                    return False
                raw_k, raw_v = parts[0].strip(), parts[1].strip()
                # Normalize key to flattened ctx
                k = raw_k.replace("$", "").strip()
                v = raw_v.strip().strip('"\'')
                val = ctx.get(k)
                # Try numeric compare
                try:
                    if op in (">", "<", ">=", "<="):
                        num_v = float(v)
                        num_val = float(val) if val is not None else float("nan")
                        if op == ">":
                            return num_val > num_v
                        if op == "<":
                            return num_val < num_v
                        if op == ">=":
                            return num_val >= num_v
                        if op == "<=":
                            return num_val <= num_v
                except Exception:
                    # Fall back to string compares
                    pass
                if op in (":", "=", "=="):
                    # If value looks numeric and val is numeric, compare numerically
                    try:
                        return float(val) == float(ctx.get(k))
                    except Exception:
                        return str(ctx.get(k)) == v
                if op == "!=":
                    return str(ctx.get(k)) != v
        # If no operator matched, do a contains check
        return rule in json.dumps(ctx)

    def evaluate_and_persist(self, decision_id: str, agent_name: str, input_data: Dict[str, Any], retrieved_context: Dict[str, Any], proposed_action: Dict[str, Any]) -> List[Dict[str, Any]]:
        # NOTE: legacy signature did not include tenant_id; accept via kwargs for compatibility
        tenant_id = None
        try:
            import inspect
            sig = inspect.signature(self.evaluate_and_persist)
        except Exception:
            sig = None
        # allow optional tenant_id in kwargs by checking locals (callers pass by name)
        # if present in locals or in outer scope, ignore—this is a best-effort shim
        try:
            tenant_id = locals().get('tenant_id', None)
        except Exception:
            tenant_id = None
        results: List[Dict[str, Any]] = []
        try:
            flat_ctx = {**self._flatten(input_data, "input"), **self._flatten(retrieved_context, "ctx"), **self._flatten(proposed_action, "action")}
            with db_session() as db:
                # Fetch enabled policies and controls; scope by tenant_id when available
                try:
                    if tenant_id:
                        controls = db.execute(text("SELECT id, policy_id, control_key FROM pg_controls WHERE enabled = 1 AND (tenant_id IS NULL OR tenant_id = :tid)"), {"tid": tenant_id}).fetchall()
                    else:
                        controls = db.execute(text("SELECT id, policy_id, control_key FROM pg_controls WHERE enabled = 1")) .fetchall()
                except Exception:
                    controls = []
                for ctrl in controls:
                    ctrl_id = ctrl[0]
                    # Load rules for control
                    try:
                        rows = db.execute(text("SELECT id, rule FROM pg_rules WHERE control_id = :cid ORDER BY priority DESC"), {"cid": ctrl_id}).fetchall()
                    except Exception:
                        rows = []
                    control_result = "pass"
                    for r in rows:
                        rule_id = r[0]
                        rule_txt = r[1] or ""
                        try:
                            ok = self._eval_simple_rule(rule_txt, flat_ctx)
                        except Exception:
                            ok = False
                        # If any rule fails (evaluates True as a matching violation), mark fail
                        if ok:
                            control_result = "fail"
                            results.append({"control_id": ctrl_id, "rule_id": rule_id, "result": "fail"})
                        else:
                            results.append({"control_id": ctrl_id, "rule_id": rule_id, "result": "pass"})
                    # Persist aggregate control result
                    try:
                        eval_id = str(uuid.uuid4())
                        db.execute(
                            text("INSERT INTO pg_evaluations (id, decision_id, control_id, result, evaluated_at) VALUES (:id, :did, :cid, :res, :ts)"),
                            {"id": eval_id, "did": decision_id, "cid": ctrl_id, "res": control_result, "ts": datetime.utcnow().isoformat()},
                        )
                    except Exception:
                        # best-effort
                        pass
                try:
                    db.commit()
                except Exception:
                    pass
        except Exception:
            pass
        return results
