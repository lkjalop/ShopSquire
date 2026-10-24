"""Project enrolled structured-provider predicates into the shared evidence ledger."""
from __future__ import annotations

from typing import Any, Mapping
from copy import deepcopy
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


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


def merge_preflight_authorization(data, preflight_workload_evidence):
    # Canonical local identity data is deterministic and must not disappear
    # when the live router varies its output. Merge metadata into the
    # recommendation-owned authorization envelope without changing that
    # envelope's product or commerce decision.
    projected_authorization = dict(
        data.get("workload_authorization")
        if isinstance(data.get("workload_authorization"), dict) else {}
    )
    projected_items = [
        dict(item) for item in list(projected_authorization.get("evidence") or [])
        if isinstance(item, dict)
    ]
    for canonical_item in preflight_workload_evidence:
        canonical_item = dict(canonical_item)
        if (
            str(canonical_item.get("status") or "").strip().lower() == "resolved"
            and not list(canonical_item.get("compiled_requirements") or [])
        ):
            try:
                from src.app.services.recommendation_core.workload_grounding import (
                    compile_workload_evidence_requirements,
                )

                _preflight_compilation = compile_workload_evidence_requirements(
                    canonical_item,
                    kind=str(canonical_item.get("kind") or "workload"),
                    product_type=str(
                        (data.get("decision") or {}).get("requested_product_node")
                        or (data.get("decision") or {}).get("node_handle") or ""
                    ),
                    name=str(
                        canonical_item.get("canonical_title")
                        or canonical_item.get("resolved_name")
                        or canonical_item.get("requested_name")
                        or "workload"
                    ),
                )
                canonical_item["compiled_requirements"] = [
                    item.model_dump() for item in _preflight_compilation.requirements
                ]
                canonical_item["claim_rejections"] = list(
                    _preflight_compilation.rejections
                )
            except Exception as exc:
                logger.debug(
                    "canonical workload requirement projection skipped: %s", exc,
                )
        canonical_key = str(
            canonical_item.get("app_id")
            or canonical_item.get("canonical_title")
            or canonical_item.get("resolved_name")
            or ""
        ).strip().lower()
        match_index = next((
            index for index, item in enumerate(projected_items)
            if canonical_key and canonical_key in {
                str(item.get("app_id") or "").strip().lower(),
                str(item.get("canonical_title") or "").strip().lower(),
                str(item.get("resolved_name") or "").strip().lower(),
            }
        ), None)
        if match_index is None:
            projected_items.append(dict(canonical_item))
        else:
            projected_items[match_index] = merge_preflight_identity(
                projected_items[match_index], canonical_item,
            )
    projected_authorization["evidence"] = projected_items
    projected_authorization.setdefault("status", "evidence_resolved_catalog_pending")
    projected_authorization.setdefault("reason", "canonical_identity_preflight")
    return projected_authorization
