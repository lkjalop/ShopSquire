from __future__ import annotations

from typing import Any, Dict
import os

from src.app.policy.gate import evaluate_policy_gate
from src.app.security.observer import analyze_payload


DEFAULT_DENY_INTENTS = {
    "execute_shell",
    "run_shell",
    "dump_database",
    "export_all_data",
    "read_secrets",
    "rotate_keys_without_approval",
}


def _env_set(name: str) -> set[str]:
    raw = str(os.getenv(name, "") or "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def evaluate_tool_intent(
    *,
    tool_name: str,
    params: Dict[str, Any] | None = None,
    runtime: str = "generic",
    tenant_id: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    """Deterministic execution-time tool-intent gate.

    Returns:
      {
        "allow": bool,
        "reason": str,
        "action": "allow"|"review"|"security_review",
        "rule_hits": {...},
        "severity": str
      }
    """
    tname = str(tool_name or "").strip().lower()
    p = params if isinstance(params, dict) else {}
    deny = set(DEFAULT_DENY_INTENTS) | _env_set("GLOBAL_TOOL_INTENT_DENYLIST")
    allow = _env_set("GLOBAL_TOOL_INTENT_ALLOWLIST")

    if tname in deny:
        return {
            "allow": False,
            "reason": "tool_intent_denylist",
            "action": "security_review",
            "rule_hits": {"tool_intent_denylist": 1.0},
            "severity": "high",
        }
    if allow and tname not in allow:
        return {
            "allow": False,
            "reason": "tool_intent_not_allowlisted",
            "action": "security_review",
            "rule_hits": {"tool_intent_not_allowlisted": 1.0},
            "severity": "high",
        }

    sec = {}
    try:
        sec = analyze_payload(
            {
                "tool_name": tname,
                "params": p,
                "runtime": runtime,
                "tenant_id": tenant_id,
                "trace_id": trace_id,
            }
        ) or {}
    except Exception:
        sec = {}
    severity = str(sec.get("severity") or "info").lower()
    details = sec.get("details") if isinstance(sec.get("details"), dict) else {}
    signals = details.get("signals") if isinstance(details.get("signals"), dict) else {}
    if severity in ("high", "critical") and (
        signals.get("prompt_injection")
        or signals.get("jailbreak")
        or signals.get("agentic_tool_abuse")
        or signals.get("data_exfiltration")
        or signals.get("unexpected_code_exec")
    ):
        return {
            "allow": False,
            "reason": "security_observer_high_risk",
            "action": "security_review",
            "rule_hits": {"observer_high_risk": 1.0},
            "severity": severity,
        }

    pg = evaluate_policy_gate(
        {
            "tool": tname,
            "params": p,
            "risk_score": float(sec.get("risk_adj") or 0.0) / 100.0,
            "signals": signals,
            "severity": severity,
            "ai_assisted": True,
            "tenant_profile": "merchant",
        }
    )
    if pg.decision == "deny":
        return {
            "allow": False,
            "reason": "policy_gate_deny",
            "action": pg.action or "security_review",
            "rule_hits": pg.rule_hits,
            "severity": "high",
        }
    if pg.decision == "review":
        return {
            "allow": False,
            "reason": "policy_gate_review",
            "action": "review",
            "rule_hits": pg.rule_hits,
            "severity": "medium",
        }

    return {"allow": True, "reason": "allow", "action": "allow", "rule_hits": {}, "severity": "info"}

