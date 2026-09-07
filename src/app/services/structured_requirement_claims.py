"""Project enrolled structured-provider predicates into the shared evidence ledger."""
from __future__ import annotations

from typing import Any, Mapping


def project_structured_requirement_claims(
    authorization: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return verified claim rows without granting commerce authority."""

    claims: list[dict[str, Any]] = []
    for evidence in list((authorization or {}).get("evidence") or []):
        if not isinstance(evidence, Mapping) or str(evidence.get("status") or "") != "resolved":
            continue
        for compiled in list(evidence.get("compiled_requirements") or []):
            if not isinstance(compiled, Mapping) or not compiled.get("attribute_key"):
                continue
            claims.append({
                "claim_id": str(
                    (compiled.get("source_claim_ids") or [
                        f"{evidence.get('provider_id') or 'provider'}:"
                        f"{evidence.get('app_id') or evidence.get('source_record_id') or 'record'}:"
                        f"{compiled.get('attribute_key')}"
                    ])[0]
                )[:240],
                "attribute": compiled.get("attribute_key"),
                "operator": compiled.get("operator"),
                "value": compiled.get("value"),
                "unit": compiled.get("unit"),
                "requirement_class": compiled.get("requirement_class") or "minimum",
                "authority_status": "verified_official",
                "source_id": evidence.get("provider_id") or evidence.get("source"),
                "source_url": evidence.get("source_url"),
                "observed_at": evidence.get("retrieved_at"),
            })
    return claims


__all__ = ["project_structured_requirement_claims"]
