"""Fail-closed rollout boundary for workload narration candidates.

No mode in this module grants buyer visibility.  Canary selection controls which
identities are evaluated in shadow; deterministic authorized blocks remain the
only selected buyer copy until a later, separately reviewed integration.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class NarrationRolloutPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "shadow", "canary"] = "off"
    canary_percent: int = Field(default=0, ge=0, le=100)
    policy_version: str = Field(default="workload-narration-rollout-v1", min_length=1, max_length=120)


class NarrationRolloutDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["workload-narration-rollout-decision-v1"] = (
        "workload-narration-rollout-decision-v1"
    )
    policy_version: str
    requested_mode: Literal["off", "shadow", "canary"]
    cohort_bucket: int = Field(ge=0, le=99)
    shadow_evaluation_selected: bool
    shadow_status: str
    buyer_visible: Literal[False] = False
    commercial_authority_granted: Literal[False] = False
    buyer_renderer: Literal["deterministic_authorized_blocks"] = (
        "deterministic_authorized_blocks"
    )
    fallback_reason: str
    deterministic_blocks: list[str] = Field(max_length=12)


def _bucket(tenant_id: str, identity_id: str, policy_version: str) -> int:
    material = f"{tenant_id}|{identity_id}|{policy_version}".encode()
    return int(hashlib.sha256(material).hexdigest()[:8], 16) % 100


def decide_shadow_rollout(
    decision: Mapping[str, Any],
    shadow_result: Mapping[str, Any] | None,
    *,
    tenant_id: str,
    identity_id: str,
    policy: NarrationRolloutPolicy,
) -> NarrationRolloutDecision:
    bucket = _bucket(tenant_id, identity_id, policy.policy_version)
    selected = policy.mode == "shadow" or (
        policy.mode == "canary" and bucket < policy.canary_percent
    )
    status = str((shadow_result or {}).get("status") or "not_run")
    if not selected:
        fallback = "shadow_disabled" if policy.mode == "off" else "identity_outside_canary"
    elif status != "accepted_shadow":
        fallback = f"shadow_{status}_deterministic_fallback"
    else:
        # Deliberately retained until buyer-visible rollout has a separate approval gate.
        fallback = "accepted_shadow_audit_only"
    return NarrationRolloutDecision(
        policy_version=policy.policy_version,
        requested_mode=policy.mode,
        cohort_bucket=bucket,
        shadow_evaluation_selected=selected,
        shadow_status=status,
        fallback_reason=fallback,
        deterministic_blocks=[
            str(value) for value in list(decision.get("authorized_narration_blocks") or [])[:12]
        ],
    )


def configured_rollout_policy() -> NarrationRolloutPolicy:
    mode = str(os.getenv("WORKLOAD_NARRATION_ROLLOUT_MODE") or "off").strip().lower()
    if mode not in {"off", "shadow", "canary"}:
        mode = "off"
    try:
        percent = int(os.getenv("WORKLOAD_NARRATION_CANARY_PERCENT") or 0)
    except (TypeError, ValueError):
        percent = 0
    bounded_percent = max(0, min(percent, 100)) if mode == "canary" else 0
    return NarrationRolloutPolicy(mode=mode, canary_percent=bounded_percent)


__all__ = [
    "NarrationRolloutDecision", "NarrationRolloutPolicy",
    "configured_rollout_policy", "decide_shadow_rollout",
]
