from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict

from fastapi import HTTPException

from src.app.config import get_settings, load_feature_flags
from src.app.feature_flags import get_flags as _ff_get_flags
from src.app.services.decision_log import log_trace_event


_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass
class AutonomyVerdict:
    allowed: bool
    scope: str
    reason: str
    authority: str = "feature_flags"
    source: str = "AUTONOMY"
    frameworks: list[str] = field(
        default_factory=lambda: [
            "ISO42001:Human oversight",
            "EU AI Act:Article 14",
            "NIST AI RMF:GOVERN-1.2",
            "GDPR:Article 22",
        ]
    )
    evidence_refs: list[str] = field(
        default_factory=lambda: [
            "config.feature_flags.AUTONOMY",
            "policy.kill_switch",
            "decision_trace.autonomy_governance",
        ]
    )
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_detail(self) -> Dict[str, Any]:
        return {
            "error": "autonomy_kill_switch",
            "scope": self.scope,
            "reason": self.reason,
            "authority": self.authority,
            "source": self.source,
            "frameworks": list(self.frameworks),
            "evidence_refs": list(self.evidence_refs),
            "config_snapshot": dict(self.config_snapshot),
        }

    def to_trace_payload(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = "allow" if self.allowed else "block"
        payload["control_family"] = "autonomy_governance"
        payload["bitemporal_evidence"] = True
        payload["evidence"] = {
            "source": "policy.kill_switch",
            "artifact_evidence": [
                f"scope={self.scope}",
                f"authority={self.authority}",
                f"reason={self.reason}",
            ],
            "artifact_claims": [
                {
                    "framework": "ISO42001",
                    "control": "Human oversight",
                    "claim_status": "implemented" if self.allowed else "triggered",
                    "summary": "Global autonomy authority evaluated before action execution.",
                    "evidence_refs": list(self.evidence_refs),
                },
                {
                    "framework": "EU AI Act",
                    "control": "Article 14",
                    "claim_status": "implemented" if self.allowed else "triggered",
                    "summary": "Human override / interruption path exists through a single kill-switch authority.",
                    "evidence_refs": list(self.evidence_refs),
                },
            ],
        }
        return payload


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _scope_cfg(flags: Dict[str, Any], scope: str) -> Dict[str, Any]:
    autonomy = flags.get("AUTONOMY") if isinstance(flags.get("AUTONOMY"), dict) else {}
    scopes = autonomy.get("scopes") if isinstance(autonomy.get("scopes"), dict) else {}
    cfg = scopes.get(scope) if isinstance(scopes.get(scope), dict) else {}
    return cfg


def evaluate_autonomy(
    scope: str,
    *,
    flags: Dict[str, Any] | None = None,
    context: Dict[str, Any] | None = None,
) -> AutonomyVerdict:
    cfg = flags or _ff_get_flags()
    scope_key = str(scope or "global").strip().lower() or "global"
    autonomy = cfg.get("AUTONOMY") if isinstance(cfg.get("AUTONOMY"), dict) else {}
    scope_cfg = _scope_cfg(cfg, scope_key)
    env_override = _env_bool("GLOBAL_AUTONOMY_KILL_SWITCH")
    global_flag = bool(cfg.get("KILL_SWITCH"))
    autonomy_global_disabled = bool(autonomy.get("kill_switch")) if isinstance(autonomy, dict) else False
    scope_disabled = bool(scope_cfg.get("disabled")) if isinstance(scope_cfg, dict) else False
    disabled = bool(env_override is True or global_flag or autonomy_global_disabled or scope_disabled)
    source = "AUTONOMY"
    reason = "autonomy_allowed"
    if env_override is True:
        source = "env:GLOBAL_AUTONOMY_KILL_SWITCH"
        reason = "global environment override disabled autonomous actions"
    elif global_flag:
        source = "KILL_SWITCH"
        reason = "legacy global kill switch disabled autonomous actions"
    elif autonomy_global_disabled:
        source = "AUTONOMY.kill_switch"
        reason = str(autonomy.get("reason") or "global autonomy authority disabled autonomous actions")
    elif scope_disabled:
        source = f"AUTONOMY.scopes.{scope_key}.disabled"
        reason = str(scope_cfg.get("reason") or f"scope {scope_key} disabled by autonomy authority")
    verdict = AutonomyVerdict(
        allowed=not disabled,
        scope=scope_key,
        reason=reason,
        source=source,
        config_snapshot={
            "global_kill_switch": bool(global_flag),
            "autonomy_kill_switch": bool(autonomy_global_disabled),
            "scope_disabled": bool(scope_disabled),
            "scope_reason": str(scope_cfg.get("reason") or "") if isinstance(scope_cfg, dict) else "",
            "context": dict(context or {}),
        },
    )
    return verdict


def log_autonomy_trace(
    trace_id: str | None,
    *,
    scope: str,
    verdict: AutonomyVerdict,
    source_id: str,
    target_type: str = "system",
    target_id: str | None = None,
) -> None:
    if not trace_id:
        return
    log_trace_event(
        trace_id=trace_id,
        event_type="autonomy_governance",
        source_type="policy",
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        payload=verdict.to_trace_payload(),
    )


def assert_autonomy_allowed(
    scope: str,
    *,
    flags: Dict[str, Any] | None = None,
    trace_id: str | None = None,
    source_id: str = "Autonomy_Governance_Agent",
    context: Dict[str, Any] | None = None,
    target_type: str = "system",
    target_id: str | None = None,
) -> AutonomyVerdict:
    verdict = evaluate_autonomy(scope, flags=flags, context=context)
    try:
        log_autonomy_trace(
            trace_id,
            scope=scope,
            verdict=verdict,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
        )
    except Exception:
        pass
    if verdict.allowed:
        return verdict
    raise HTTPException(status_code=503, detail=verdict.to_detail())

