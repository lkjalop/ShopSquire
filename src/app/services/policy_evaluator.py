from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import inspect, text

from src.app.models.db import db_session

_log = logging.getLogger("shopsquire.policy_evaluator")


class PolicyEvaluator:
    """Conservative evaluator for declarative PolicyGraph controls."""

    def _flatten(self, obj: Any, prefix: str = "") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else key
                out.update(self._flatten(value, path))
        elif isinstance(obj, list):
            out[prefix] = obj
            for index, value in enumerate(obj):
                out.update(self._flatten(value, f"{prefix}[{index}]"))
        else:
            out[prefix] = obj
        return out

    def _eval_simple_rule(self, rule: str, ctx: Dict[str, Any]) -> bool:
        rule = (rule or "").strip()
        if not rule:
            return False
        for operator in ("==", "!=", ">=", "<=", ">", "<", ":", "="):
            if operator not in rule:
                continue
            parts = rule.split(operator)
            if len(parts) != 2:
                return False
            raw_key, raw_value = parts[0].strip(), parts[1].strip()
            key = raw_key.replace("$", "").strip()
            expected = raw_value.strip().strip('"\'')
            actual = ctx.get(key)
            try:
                if operator == ">":
                    return float(actual) > float(expected)
                if operator == "<":
                    return float(actual) < float(expected)
                if operator == ">=":
                    return float(actual) >= float(expected)
                if operator == "<=":
                    return float(actual) <= float(expected)
            except (TypeError, ValueError):
                return False
            if operator in (":", "=", "=="):
                try:
                    return float(actual) == float(expected)
                except (TypeError, ValueError):
                    return str(actual) == expected
            if operator == "!=":
                return str(actual) != expected
        return rule in json.dumps(ctx)

    @staticmethod
    def _optional_rows(db, statement: str, params: Dict[str, Any] | None = None):
        """Isolate optional reads so a PostgreSQL error cannot abort the caller."""
        try:
            with db.begin_nested():
                return db.execute(text(statement), params or {}).fetchall()
        except Exception as exc:
            _log.warning("optional policy read failed: %s", str(exc)[:300])
            return []

    def evaluate_and_persist(
        self,
        decision_id: str,
        agent_name: str,
        input_data: Dict[str, Any],
        retrieved_context: Dict[str, Any],
        proposed_action: Dict[str, Any],
        tenant_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        del agent_name  # retained in the public signature for compatibility
        results: List[Dict[str, Any]] = []
        flat_ctx = {
            **self._flatten(input_data, "input"),
            **self._flatten(retrieved_context, "ctx"),
            **self._flatten(proposed_action, "action"),
        }
        try:
            with db_session() as db:
                try:
                    has_controls = inspect(db.get_bind()).has_table(
                        "policy_graph_controls"
                    )
                except Exception as exc:
                    _log.warning("unable to inspect policy schema: %s", str(exc)[:300])
                    has_controls = False

                if not has_controls:
                    controls = []
                elif tenant_id:
                    controls = self._optional_rows(
                        db,
                        "SELECT id, policy_id, control_key FROM policy_graph_controls "
                        "WHERE enabled IS TRUE "
                        "AND (tenant_id IS NULL OR tenant_id = :tenant_id)",
                        {"tenant_id": tenant_id},
                    )
                else:
                    controls = self._optional_rows(
                        db,
                        "SELECT id, policy_id, control_key FROM policy_graph_controls "
                        "WHERE enabled IS TRUE",
                    )

                for control in controls:
                    control_id = control[0]
                    rows = self._optional_rows(
                        db,
                        "SELECT id, rule FROM policy_graph_rules "
                        "WHERE control_id = :control_id ORDER BY priority DESC",
                        {"control_id": control_id},
                    )
                    control_result = "pass"
                    for row in rows:
                        rule_id = row[0]
                        matched_violation = self._eval_simple_rule(
                            row[1] or "", flat_ctx
                        )
                        result = "fail" if matched_violation else "pass"
                        if matched_violation:
                            control_result = "fail"
                        results.append(
                            {
                                "control_id": control_id,
                                "rule_id": rule_id,
                                "result": result,
                            }
                        )
                    try:
                        with db.begin_nested():
                            db.execute(
                                text(
                                    "INSERT INTO policy_graph_evaluations "
                                    "(id, decision_id, control_id, result, evaluated_at) "
                                    "VALUES (:id, :decision_id, :control_id, :result, :evaluated_at)"
                                ),
                                {
                                    "id": str(uuid.uuid4()),
                                    "decision_id": decision_id,
                                    "control_id": control_id,
                                    "result": control_result,
                                    "evaluated_at": datetime.utcnow().isoformat(),
                                },
                            )
                    except Exception as exc:
                        _log.warning(
                            "policy evaluation persistence failed for control=%s: %s",
                            control_id,
                            str(exc)[:300],
                        )
                db.commit()
        except Exception as exc:
            _log.warning("policy evaluation failed: %s", str(exc)[:300])
        return results
