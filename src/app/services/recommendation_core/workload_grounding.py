"""Governed external evidence for named workloads.

The router may identify a name from unbounded language. This module never trusts that name
as a requirement: it resolves evidence through an enrolled connector, validates provenance,
and returns registry-shaped constraints for the shared fit engine.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any, Dict, Iterable, Tuple


_STEAM_HOST = "store.steampowered.com"


def _enabled_flag() -> bool:
    override = os.getenv("STEAM_REQUIREMENTS_LIVE_ENABLED")
    if override is not None:
        return override.strip().lower() in ("1", "true", "yes", "on")
    try:
        from src.app.config import get_settings, load_feature_flags
        return bool(load_feature_flags(get_settings().feature_flags_path).get(
            "STEAM_REQUIREMENTS_LIVE_ENABLED", False))
    except Exception:
        return False


def _source_enrolled() -> bool:
    try:
        from src.app.platform.store_profile import profile_slot
        allowed = profile_slot("external_research_allowlist", default=[]) or []
    except Exception:
        return False
    for value in allowed:
        candidate = str(value or "").strip()
        host = (urlparse(candidate).hostname if "://" in candidate else candidate).lower()
        if host == _STEAM_HOST:
            return True
    return False


def live_steam_allowed(*, consent: bool) -> bool:
    """All three gates are mandatory: buyer consent, operator flag, enrolled source."""
    return bool(consent and _enabled_flag() and _source_enrolled())


def _minimum_constraints(requirements: Dict[str, Any]) -> Dict[str, Tuple[str, float]]:
    minimum = requirements.get("minimum") or {}
    out: Dict[str, Tuple[str, float]] = {}
    ram = minimum.get("ram_gb")
    storage = minimum.get("storage_gb")
    if isinstance(ram, (int, float)) and 1 <= float(ram) <= 512:
        out["ram_gb"] = (">=", float(ram))
    if isinstance(storage, (int, float)) and 1 <= float(storage) <= 8192:
        out["storage_gb"] = (">=", float(storage))
    try:
        from src.app.services.gpu_translation import desktop_req_to_laptop_tier
        translated = desktop_req_to_laptop_tier(str(minimum.get("gpu") or "")) or {}
        vram = translated.get("vram_gb_min")
        if isinstance(vram, (int, float)) and 0 <= float(vram) <= 128:
            out["gpu_vram_gb"] = (">=", float(vram))
    except Exception:
        pass
    return out


def compile_workload_evidence_requirements(
    result: Dict[str, Any], *, kind: str, name: str, product_type: str = "el-6",
):
    """Compile one enrolled provider record into registry-authorized receipts.

    Both recommendation execution and the revision-bound buyer projection call
    this function.  Keeping a single compiler boundary prevents the UI from
    showing ``identity only`` after the fit engine has already applied official
    RAM/VRAM predicates.
    """
    from src.app.services.recommendation_core.requirement_compiler import (
        compile_authoritative_requirements,
    )

    canonical_name = str(result.get("canonical_title") or result.get("resolved_name") or name)[:160]
    claims = []
    for attr, predicate in _minimum_constraints(result).items():
        claims.append({
            "need_id": f"{kind}:{attr}",
            "subject_span": str(name)[:120],
            "artefact_name": canonical_name,
            "claim_type": "minimum_requirements",
            "status": "accepted",
            "source_id": result.get("source") or result.get("provider_id"),
            "source_record_id": result.get("source_record_id") or result.get("app_id"),
            "observed_at": result.get("retrieved_at"),
            "confidence": result.get("confidence"),
            "attribute_key": attr,
            "operator": predicate[0],
            "value": predicate[1],
            "authority": "official_requirements",
            "lineage_root": result.get("source") or result.get("provider_id"),
            # This predicate came from a comparison table, not the publisher's
            # literal hardware requirement. The compiler must not promote it.
            "claim_origin": "derived" if attr == "gpu_vram_gb" else "observed",
            "source_excerpt": (
                str((result.get("minimum") or {}).get("gpu") or "")[:1000]
                if attr == "gpu_vram_gb" else None
            ),
        })
    # These are exact literal predicates, not performance equivalences. An
    # unsplit alternative or qualified model string cannot match a different
    # catalog model. Richer interpretation still needs cited typed extraction.
    minimum = result.get("minimum") or {}
    receipts = minimum.get("source_fields") or {}
    for field, attribute in (("cpu", "cpu_model"), ("gpu", "gpu_model"),
                             ("os", "os"), ("storage_type", "storage_type")):
        receipt = receipts.get(field) if isinstance(receipts, dict) else None
        if not isinstance(receipt, dict):
            continue
        excerpt, start, end = receipt.get("text"), receipt.get("start"), receipt.get("end")
        value = minimum.get(field)
        if not (isinstance(value, str) and isinstance(excerpt, str) and len(excerpt) <= 1024
                and type(start) is int and type(end) is int
                and 0 <= start < end <= len(excerpt) and excerpt[start:end] == value
                and receipt.get("representation") == "steam_requirement_line_v1"
                and (result.get("source") or result.get("provider_id")) == "steam"):
            continue
        claims.append({
            "subject_span": str(name)[:120], "artefact_name": canonical_name,
            "status": "accepted", "authority": "official_requirements",
            "claim_origin": "observed", "source_id": "steam", "lineage_root": "steam",
            "source_record_id": result.get("source_record_id") or result.get("app_id"),
            "observed_at": result.get("retrieved_at"), "confidence": result.get("confidence"),
            "attribute_key": attribute, "operator": "in", "value": [value],
            "source_excerpt": excerpt, "value_spans": [[start, end]],
            "requirement_class": "minimum",
        })
    from src.app.platform.store_profile import active_profile_id
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope
    # This adapter translates computer-host requirements, not arbitrary retail
    # product claims. A tenant profile without a computer-host policy abstains.
    scope = resolve_requirement_scope(
        tenant_id=current_tenant_id(), profile_id=active_profile_id(),
        product_type=product_type, relationship="RUN_SUBJECT_ON_PRODUCT",
    )
    return compile_authoritative_requirements(claims, scope=scope)


def resolve_named_workloads(
    entities: Iterable[Tuple[str, str]], *, consent: bool, product_type: str = "el-6",
) -> Dict[str, Any]:
    """Resolve clamped workload entities into authorized minimum constraints.

    The model identifies the entity kind and literal name.  An enrolled provider
    must resolve that entity before its requirements can authorize catalog fit.
    Unsupported or unavailable providers remain explicit unresolved evidence;
    they never fall through to a generic workload profile silently.
    """
    from src.app.services.connectors.workload_evidence import default_registry

    registry = default_registry()
    requirements: Dict[str, list[Tuple[str, Any]]] = {}
    evidence = []
    seen = set()
    for raw_kind, name in list(entities)[:3]:
        kind = str(raw_kind or "").strip().lower()
        key = f"{kind}:{str(name or '').strip().lower()}"
        if not key or key in seen:
            continue
        seen.add(key)
        enrolled_providers = registry.provider_ids_for(kind)
        # Steam readiness is game-specific. Software and other workloads must
        # not inherit it just because the buyer consented to research.
        allow_live = bool(kind == "game" and live_steam_allowed(consent=consent))
        typed, provider_attempts = registry.resolve_with_trace(
            kind, name, allow_live=allow_live,
        )
        result = typed.to_dict() if typed is not None else None
        if not result:
            evidence.append({
                "kind": kind, "requested_name": name, "status": "not_resolved",
                "live_allowed": allow_live,
                "reason": "no_enrolled_provider_result",
                "provider_attempts": provider_attempts,
                "provider_coverage": "none_for_kind" if not provider_attempts else "attempted",
                "enrolled_providers": list(enrolled_providers),
            })
            continue
        compilation = compile_workload_evidence_requirements(
            result, kind=kind, name=name, product_type=product_type,
        )
        if not compilation.requirements:
            evidence.append({
                "kind": kind,
                "requested_name": name,
                "resolved_name": result.get("resolved_name") or result.get("title"),
                "canonical_title": result.get("canonical_title") or result.get("resolved_name"),
                "publisher": result.get("publisher"),
                "app_id": result.get("app_id") or result.get("source_record_id"),
                "release_state": result.get("release_state"),
                "release_date": result.get("release_date"),
                "requirements_completeness": (
                    result.get("requirements_completeness") or "identity_only"
                ),
                "status": "identity_resolved_requirements_incomplete",
                "live_allowed": allow_live,
                "source": result.get("source"),
                "source_url": result.get("source_url"),
                "retrieved_at": result.get("retrieved_at"),
                "cached": bool(result.get("cached")),
                "confidence": result.get("confidence"),
                "identity_resolution": dict(result.get("identity_resolution") or {}),
                "minimum": dict(result.get("minimum") or {}),
                "literal_requirement_observations": list(result.get("literal_requirement_observations") or []),
                "recommended": dict(result.get("recommended") or {}),
                "provider_attempts": provider_attempts,
                "provider_coverage": "identity_only",
                "enrolled_providers": list(enrolled_providers),
                "compiled_requirements": [],
                "claim_rejections": list(compilation.rejections),
                "reason": "official_identity_has_no_material_hardware_requirements",
            })
            continue
        for compiled in compilation.requirements:
            attr = compiled.attribute_key
            # Preserve typed predicates. The shared constraint engine owns
            # intersection/conflict handling; a numeric max loses upper bounds
            # and cannot represent categorical requirements.
            predicate = (compiled.operator, compiled.value)
            predicates = requirements.setdefault(attr, [])
            if predicate not in predicates:
                predicates.append(predicate)
        evidence.append({
            "kind": kind,
            "requested_name": name,
            "resolved_name": result.get("resolved_name") or result.get("canonical_title"),
            "canonical_title": result.get("canonical_title") or result.get("resolved_name"),
            "publisher": result.get("publisher"),
            "app_id": result.get("app_id") or result.get("source_record_id"),
            "release_state": result.get("release_state"),
            "release_date": result.get("release_date"),
            "requirements_completeness": result.get("requirements_completeness"),
            "status": "resolved",
            "live_allowed": allow_live,
            "source": result.get("source"),
            "provider_id": result.get("provider_id") or result.get("source"),
            "source_url": result.get("source_url"),
            "retrieved_at": result.get("retrieved_at"),
            "cached": bool(result.get("cached")),
            "confidence": result.get("confidence"),
            "provenance_chain": list(result.get("provenance_chain") or []),
            "minimum": dict(result.get("minimum") or {}),
            "literal_requirement_observations": list(result.get("literal_requirement_observations") or []),
            "recommended": dict(result.get("recommended") or {}),
            "requested_target": dict(result.get("requested_target") or {}),
            "provider_attempts": provider_attempts,
            "provider_coverage": "resolved",
            "enrolled_providers": list(enrolled_providers),
            "compiled_requirements": [
                item.model_dump() for item in compilation.requirements
            ],
            "claim_rejections": list(compilation.rejections),
        })
        if len(evidence) >= 2:
            break
    return {
        "requirements": requirements,
        "evidence": evidence,
        "consent_recorded": bool(consent),
        "live_allowed": any(bool(item.get("live_allowed")) for item in evidence),
    }


def resolve_canonical_workload_identity(
    identity_resolution: Dict[str, Any] | None,
    *,
    workload_kind_hints: Iterable[str],
    consent: bool,
    product_type: str = "el-6",
) -> Dict[str, Any]:
    """Re-query enrolled structured providers after cited identity resolution.

    The first recommendation pass can only use the buyer's literal phrase.  An
    unfamiliar title may therefore miss a structured provider even though the
    later governed discovery stage resolves its canonical spelling.  This
    adapter performs one bounded second lookup using that cited title. It does
    not maintain title aliases. The kind normally comes from the turn router;
    a cited structured-store origin may also provide the bounded provider kind.
    """

    resolution = dict(identity_resolution or {})
    identity = dict(resolution.get("identity") or {})
    canonical_title = str(identity.get("canonical_title") or "").strip()
    if resolution.get("status") != "resolved" or not canonical_title:
        return {
            "status": "not_attempted",
            "failure_code": "canonical_identity_not_resolved",
            "requirements": {},
            "evidence": [],
        }
    kinds: list[str] = []
    for value in workload_kind_hints:
        kind = str(value or "").strip().lower()
        if kind in {"game", "software"} and kind not in kinds:
            kinds.append(kind)
    if not kinds:
        # A Steam row already clamped by identity resolution is a grounded
        # provider-kind hint. This authorizes only another structured lookup;
        # requirements and product fit still require the normal compilation
        # and policy gates.
        cited_rows = list(resolution.get("cited_rows") or [])
        if any(
            (
                "store.steampowered.com" in str(row.get("url") or "").casefold()
                or str(row.get("registrable_domain") or "").casefold()
                == "store.steampowered.com"
            )
            for row in cited_rows
            if isinstance(row, dict)
        ):
            kinds.append("game")
    if not kinds:
        # Identity resolution has already produced a cited canonical title.
        # Ask the small, enrolled provider registry which bounded capability
        # owns it instead of requiring the language router to know the tool in
        # advance. Every provider still performs its own exact identity check,
        # and this fan-out grants no evidence when all providers reject it.
        kinds.extend(("game", "software"))
    result = resolve_named_workloads(
        [(kind, canonical_title) for kind in kinds[:2]],
        consent=consent,
        product_type=product_type,
    )
    resolved = any(
        str(item.get("status") or "").strip().lower() == "resolved"
        and bool(item.get("compiled_requirements"))
        for item in result.get("evidence") or []
        if isinstance(item, dict)
    )
    # A language model's entity kind is a proposal, not provider authority.
    # If the cited canonical identity misses the proposed provider class, try
    # the remaining enrolled class once. This is a bounded capability lookup,
    # not an application alias or a title-specific correction.
    remaining_kinds = [kind for kind in ("game", "software") if kind not in kinds]
    if not resolved and remaining_kinds:
        fallback = resolve_named_workloads(
            [(kind, canonical_title) for kind in remaining_kinds],
            consent=consent,
            product_type=product_type,
        )
        merged_requirements = dict(result.get("requirements") or {})
        merged_requirements.update(dict(fallback.get("requirements") or {}))
        result = {
            **result,
            "requirements": merged_requirements,
            "evidence": [
                *list(result.get("evidence") or []),
                *list(fallback.get("evidence") or []),
            ],
            "live_allowed": bool(
                result.get("live_allowed") or fallback.get("live_allowed")
            ),
            "provider_kind_fallback_used": True,
        }
        resolved = any(
            str(item.get("status") or "").strip().lower() == "resolved"
            and bool(item.get("compiled_requirements"))
            for item in result.get("evidence") or []
            if isinstance(item, dict)
        )
    return {
        **result,
        "status": "resolved" if resolved else "not_resolved",
        "canonical_title": canonical_title,
        "lookup_basis": "cited_canonical_identity",
        "failure_code": None if resolved else "structured_provider_no_authoritative_result",
    }


def resolve_unresolved_concepts(
    concepts: Iterable[str], *, workload_kind_hints: Iterable[str], consent: bool,
    product_type: str = "el-6",
) -> Dict[str, Any]:
    """Try the cheapest enrolled identity+requirements providers before open web.

    Concepts are buyer-authored or coverage-clamped spans. Trying a provider
    grants no authority unless that provider independently resolves the exact
    identity and compiles its official requirements.
    """

    kinds = [
        str(value).strip().lower() for value in workload_kind_hints
        if str(value).strip().lower() in {"game", "software"}
    ]
    if not kinds:
        kinds = ["game", "software"]
    entities: list[tuple[str, str]] = []
    for raw in list(concepts)[:3]:
        concept = " ".join(str(raw or "").split()).strip()[:160]
        if not concept:
            continue
        entities.extend((kind, concept) for kind in kinds[:2])
    if not entities:
        return {
            "status": "not_attempted", "failure_code": "no_bounded_identity_concept",
            "requirements": {}, "evidence": [],
        }
    result = resolve_named_workloads(entities, consent=consent, product_type=product_type)
    resolved = any(
        isinstance(item, dict)
        and item.get("status") == "resolved"
        and bool(item.get("compiled_requirements"))
        for item in result.get("evidence") or []
    )
    return {
        **result,
        "status": "resolved" if resolved else "not_resolved",
        "lookup_basis": "buyer_concept_enrolled_provider_first",
        "failure_code": None if resolved else "structured_provider_no_authoritative_result",
    }


def resolve_named_games(entities: Iterable[Tuple[str, str]], *, consent: bool) -> Dict[str, Any]:
    """Compatibility alias for callers migrating to source-neutral workloads."""
    return resolve_named_workloads(entities, consent=consent)
