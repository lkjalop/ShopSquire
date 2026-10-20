"""Project enrolled structured-provider predicates into the shared evidence ledger."""
from __future__ import annotations

from typing import Any, Mapping
from copy import deepcopy
import hashlib
import json


def merge_preflight_identity(current: Mapping[str, Any], preflight: Mapping[str, Any]) -> dict[str, Any]:
    """Fill identity metadata only; executed evidence/failure state always wins."""
    result = deepcopy(dict(current))
    for key in ("app_id", "canonical_title", "resolved_name", "publisher"):
        if not result.get(key) and preflight.get(key):
            result[key] = deepcopy(preflight[key])
    return result


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
                    "compilation_scope", "source_excerpt", "value_spans",
                    "source_id", "source_record_id", "observed_at", "expires_at",
                    "applicability", "simulation_only",
                )},
            }
            claim_id = "req-" + hashlib.sha256(json.dumps(
                identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode("utf-8")).hexdigest()
            # The ledger is a snapshot, not a mutable view of provider output.
            # Preserve the compiler's cited alternatives without inferring any
            # additional equivalence or upgrading their verification status.
            claims.append(deepcopy({
                "claim_id": claim_id,
                "source_claim_ids": identity["source_claim_ids"],
                "compilation_scope": compiled.get("compilation_scope"),
                "source_excerpt": compiled.get("source_excerpt"),
                "value_spans": compiled.get("value_spans") or [],
                "source_revision": compiled.get("source_revision"),
                "artefact_name": compiled.get("artefact_name"),
                "artefact_version": compiled.get("artefact_version"),
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
                "source_id": compiled.get("source_id") or evidence.get("provider_id") or evidence.get("source"),
                "source_record_id": compiled.get("source_record_id"),
                "source_url": evidence.get("source_url"),
                "observed_at": compiled.get("observed_at") or evidence.get("retrieved_at"),
                "expires_at": compiled.get("expires_at"),
                "revoked_at": compiled.get("revoked_at"),
                "applicability": compiled.get("applicability"),
                "simulation_only": compiled.get("simulation_only") is True,
            }))
    return claims


__all__ = ["project_structured_requirement_claims"]
