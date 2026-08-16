from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.app.services.operator_tenant_membership import (
    grant_membership,
    principal_hash_for_api_key,
)


DEFAULT_PROFILE_PATH = Path("config/portfolio_pilot_identities.json")
ALLOWED_ROLES = {"merchant", "owner", "developer"}


@dataclass(frozen=True)
class PilotPrincipal:
    subject_id: str
    display_name: str
    role: str
    credential_env: str


@dataclass(frozen=True)
class PilotIdentityProfile:
    tenant_id: str
    environment_class: str
    production_authority: bool
    principals: tuple[PilotPrincipal, ...]
    supplier_mode: str
    real_supplier_send_authorized: bool


def load_pilot_identity_profile(path: Path = DEFAULT_PROFILE_PATH) -> PilotIdentityProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "portfolio-pilot-identities-v1":
        raise ValueError("unsupported_pilot_identity_profile")
    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ValueError("pilot_tenant_required")
    principals: list[PilotPrincipal] = []
    seen_subjects: set[str] = set()
    for raw in payload.get("principals") or []:
        subject = str(raw.get("subject_id") or "").strip()
        role = str(raw.get("role") or "").strip()
        credential_env = str(raw.get("credential_env") or "").strip()
        if not subject or subject in seen_subjects:
            raise ValueError("pilot_subject_missing_or_duplicate")
        if role not in ALLOWED_ROLES:
            raise ValueError("unsupported_pilot_role")
        if credential_env not in {"MERCHANT_API_KEY", "OWNER_API_KEY", "DEVELOPER_API_KEY"}:
            raise ValueError("pilot_credential_env_not_role_bound")
        seen_subjects.add(subject)
        principals.append(
            PilotPrincipal(
                subject_id=subject,
                display_name=str(raw.get("display_name") or subject).strip(),
                role=role,
                credential_env=credential_env,
            )
        )
    if not principals:
        raise ValueError("pilot_principals_required")
    real_send = bool(payload.get("real_supplier_send_authorized"))
    supplier_mode = str(payload.get("supplier_mode") or "").strip()
    if real_send or supplier_mode != "synthetic_only":
        raise ValueError("portfolio_pilot_must_prohibit_real_supplier_send")
    return PilotIdentityProfile(
        tenant_id=tenant_id,
        environment_class=str(payload.get("environment_class") or "").strip(),
        production_authority=bool(payload.get("production_authority")),
        principals=tuple(principals),
        supplier_mode=supplier_mode,
        real_supplier_send_authorized=real_send,
    )


def enrol_pilot_identities(db, profile: PilotIdentityProfile) -> dict[str, Any]:
    if profile.production_authority:
        raise ValueError("local_pilot_cannot_claim_production_authority")
    credentials = {
        principal.credential_env: str(os.getenv(principal.credential_env) or "")
        for principal in profile.principals
    }
    missing = sorted(name for name, value in credentials.items() if not value)
    if missing:
        raise ValueError("missing_pilot_credentials:" + ",".join(missing))
    enrolled: list[dict[str, str]] = []
    for principal in profile.principals:
        credential = credentials[principal.credential_env]
        principal_hash = principal_hash_for_api_key(credential)
        grant_membership(
            db,
            principal_hash=principal_hash,
            tenant_id=profile.tenant_id,
            role=principal.role,
            subject_id=principal.subject_id,
            auth_method="api_key",
            created_by="portfolio-pilot-enrolment",
        )
        enrolled.append(
            {
                "subject_id": principal.subject_id,
                "display_name": principal.display_name,
                "role": principal.role,
                "credential_env": principal.credential_env,
            }
        )
    db.commit()
    return {
        "tenant_id": profile.tenant_id,
        "identity_source": "server_persisted_membership",
        "enrolled": enrolled,
        "supplier_mode": profile.supplier_mode,
        "real_supplier_send_authorized": False,
    }


def pilot_identity_readiness(db, profile: PilotIdentityProfile) -> dict[str, Any]:
    rows = db.execute(
        text(
            "SELECT subject_id, role, status FROM operator_tenant_membership "
            "WHERE tenant_id=:tenant"
        ),
        {"tenant": profile.tenant_id},
    ).fetchall()
    observed = {
        (str(row[0] or ""), str(row[1] or "")): str(row[2] or "")
        for row in rows
    }
    principals = [
        {
            "subject_id": item.subject_id,
            "display_name": item.display_name,
            "role": item.role,
            "status": observed.get((item.subject_id, item.role), "not_enrolled"),
        }
        for item in profile.principals
    ]
    ready = all(item["status"] == "active" for item in principals)
    return {
        "tenant_id": profile.tenant_id,
        "ready": ready,
        "identity_source": "server_persisted_membership",
        "environment_class": profile.environment_class,
        "production_authority": False,
        "principals": principals,
        "supplier_mode": profile.supplier_mode,
        "real_supplier_send_authorized": False,
    }


__all__ = [
    "PilotIdentityProfile",
    "PilotPrincipal",
    "enrol_pilot_identities",
    "load_pilot_identity_profile",
    "pilot_identity_readiness",
]
