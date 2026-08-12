"""Tenant-bound authenticated staff identity for incident collaboration."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import (
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    OperatorSubject,
    operator_subject,
    require_role,
)


@dataclass(frozen=True)
class IncidentStaffPrincipal:
    role: str
    subject_id: str
    tenant_id: str
    identity_source: str


def require_incident_staff_principal(
    request: Request,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
    subject: OperatorSubject = Depends(operator_subject),
) -> IncidentStaffPrincipal:
    membership = getattr(request.state, "operator_identity", None)
    tenant_id = str(getattr(membership, "tenant_id", None) or current_tenant_id())
    subject_id = str(getattr(membership, "subject_id", None) or subject.user_id or f"shared-key:{role}")
    return IncidentStaffPrincipal(
        role=role,
        subject_id=subject_id,
        tenant_id=tenant_id,
        identity_source="tenant_membership" if getattr(membership, "persisted", False) else "authenticated_role_audit_mode",
    )
