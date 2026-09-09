"""Project enrolled structured-provider predicates into the shared evidence ledger."""
from __future__ import annotations

from typing import Any, Mapping
import hashlib
import json


def project_structured_requirement_claims(
    authorization: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Preserve verification status without granting new claim authority."""

    claims: list[dict[str, Any]] = []
    for evidence in list((authorization or {}).get("evidence") or []):
        if not isinstance(evidence, Mapping) or str(evidence.get("status") or "") != "resolved":
            continue
        for compiled in list(evidence.get("compiled_requirements") or []):
            if not isinstance(compiled, Mapping) or not compiled.get("attribute_key"):
                continue
            # A provider record can establish many predicates. Its identifier is
            # provenance, never the identity of an editable requirement claim.
            identity = {
                "provider": evidence.get("provider_id") or evidence.get("source"),
                "record": evidence.get("app_id") or evidence.get("source_record_id"),
                "origin": evidence.get("source_url"),
                "source_claim_ids": sorted(str(v) for v in compiled.get("source_claim_ids") or []),
                **{key: compiled.get(key) for key in (
                    "attribute_key", "operator", "value", "unit", "requirement_class",
                    "scope_caveat", "source_revision", "artefact_name", "artefact_version",
                )},
            }
            claim_id = "req-" + hashlib.sha256(json.dumps(
                identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")).hexdigest()
            claims.append({
                "claim_id": claim_id,
                "source_claim_ids": identity["source_claim_ids"],
                "compilation_scope": compiled.get("compilation_scope"),
                "attribute": compiled.get("attribute_key"),
                "operator": compiled.get("operator"),
                "value": compiled.get("value"),
                "unit": compiled.get("unit"),
                "requirement_class": compiled.get("requirement_class") or "minimum",
                "constraint_tier": "required",
                "condition": compiled.get("scope_caveat"),
                "authority_status": (
                    "verified_official" if compiled.get("verification_status") == "verified"
                    else "observed_held"
                ),
                "source_id": evidence.get("provider_id") or evidence.get("source"),
                "source_url": evidence.get("source_url"),
                "observed_at": evidence.get("retrieved_at"),
            })
    return claims


__all__ = ["project_structured_requirement_claims"]
