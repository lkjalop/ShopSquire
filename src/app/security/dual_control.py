"""Dual-control (two-person integrity) for sensitive writes — shared primitive.

IT-PREV-01: a write that GRANTS or REPOINTS trust (a supplier's verified domain, a vendor contact
address, a trust status → verified) must be approved by a SECOND owner/developer whose key differs
from the requestor's, so a single compromised admin credential cannot repoint where the platform's
autonomous RFQs are sent. Extracted from admin_supply_chain so the KYV control plane shares it.

Reducing trust (suspend/revoke) is deliberately NOT gated — incident response must stay fast.

Env: SUPPLY_CHAIN_DUAL_CONTROL=0 disables; enforced only outside local/dev/test. Never a silent
bypass — a missing/invalid approver raises 403 and a bypass attempt emits an insider-threat signal.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import HTTPException, Request, status

from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, get_role_from_key

logger = logging.getLogger("shopsquire.dual_control")


def dual_control_enabled() -> bool:
    return os.getenv("SUPPLY_CHAIN_DUAL_CONTROL", "1").lower() not in ("0", "false", "no")


def require_dual_control(
    request: Request,
    primary_role: str,
    x_api_key: Optional[str],
    x_approver_token: Optional[str],
    *,
    action_label: str = "sensitive_write",
) -> None:
    """Enforce a distinct second owner/developer approver. No-op when disabled or in local/dev/test.
    Raises 403 on a missing/self/under-privileged approver."""
    if not dual_control_enabled():
        return
    env = str(os.getenv("APP_ENV", "local") or "local").lower()
    if env in ("local", "dev", "development", "test", "testing"):
        return

    if not x_approver_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"dual_control_required: {action_label} needs X-Approver-Token from a second owner/developer",
        )
    # One person cannot approve their own change.
    if x_approver_token.strip() == (x_api_key or "").strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dual_control_violation: approver token must differ from requestor token",
        )
    approver_role = get_role_from_key(x_approver_token.strip())
    if approver_role not in (ROLE_OWNER, ROLE_DEVELOPER):
        try:
            from src.app.security.insider_threat_detector import InsiderThreatSignal, _emit as _it_emit
            _it_emit(InsiderThreatSignal(
                signal_type="dual_control_bypass_attempt",
                actor=x_api_key or "unknown",
                resource=getattr(request.url, "path", "/admin"),
                severity="critical",
                context={"approver_role": approver_role, "required_roles": [ROLE_OWNER, ROLE_DEVELOPER],
                         "action": action_label},
            ))
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dual_control_violation: approver must hold owner or developer role",
        )
    logger.info("dual_control_approved action=%s primary_role=%s approver_role=%s path=%s",
                action_label, primary_role, approver_role, getattr(request.url, "path", ""))
