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
    result: Dict[str, Any], *, kind: str, name: str,
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

    claims = []
    for attr, predicate in _minimum_constraints(result).items():
        claims.append({
            "need_id": f"{kind}:{attr}",
            "subject_span": str(name)[:120],
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
        })
    return compile_authoritative_requirements(claims)


def resolve_named_workloads(
    entities: Iterable[Tuple[str, str]], *, consent: bool,
) -> Dict[str, Any]:
    """Resolve clamped workload entities into authorized minimum constraints.

    The model identifies the entity kind and literal name.  An enrolled provider
    must resolve that entity before its requirements can authorize catalog fit.
    Unsupported or unavailable providers remain explicit unresolved evidence;
    they never fall through to a generic workload profile silently.
    """
    from src.app.services.connectors.workload_evidence import default_registry

    registry = default_registry()
    requirements: Dict[str, Tuple[str, float]] = {}
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
            result, kind=kind, name=name,
        )
        if not compilation.requirements:
            evidence.append({
                "kind": kind,
                "requested_name": name,
                "resolved_name": result.get("resolved_name") or result.get("title"),
                "status": "identity_resolved_requirements_incomplete",
                "live_allowed": allow_live,
                "source": result.get("source"),
                "source_url": result.get("source_url"),
                "retrieved_at": result.get("retrieved_at"),
                "cached": bool(result.get("cached")),
                "confidence": result.get("confidence"),
                "identity_resolution": dict(result.get("identity_resolution") or {}),
                "minimum": dict(result.get("minimum") or {}),
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
            predicate = (compiled.operator, float(compiled.value))
            current = requirements.get(attr)
            if current is None or predicate[1] > current[1]:
                requirements[attr] = predicate
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
    )
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


def resolve_named_games(entities: Iterable[Tuple[str, str]], *, consent: bool) -> Dict[str, Any]:
    """Compatibility alias for callers migrating to source-neutral workloads."""
    return resolve_named_workloads(entities, consent=consent)
