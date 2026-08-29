"""Bounded registry for official workload requirement providers.

Providers resolve a model-identified workload name into typed evidence. They do
not select products or authorize constraints; the shared capability layer does.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Protocol


@dataclass(frozen=True)
class WorkloadTarget:
    resolution: Optional[str] = None
    fps: Optional[int] = None
    ray_tracing: Optional[bool] = None
    api_compatibility: tuple[str, ...] = ()
    architecture_compatibility: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkloadEvidence:
    kind: str
    requested_name: str
    resolved_name: str
    provider_id: str
    status: str
    minimum: Dict[str, Any] = field(default_factory=dict)
    recommended: Dict[str, Any] = field(default_factory=dict)
    requested_target: WorkloadTarget = field(default_factory=WorkloadTarget)
    source_url: Optional[str] = None
    source_record_id: Optional[str] = None
    retrieved_at: Optional[str] = None
    cached: bool = False
    confidence: float = 0.0
    provenance_chain: tuple[str, ...] = ()
    identity_resolution: Dict[str, Any] = field(default_factory=dict)
    canonical_title: Optional[str] = None
    publisher: Optional[str] = None
    app_id: Optional[str] = None
    release_state: Optional[str] = None
    release_date: Optional[str] = None
    requirements_completeness: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["provenance_chain"] = list(self.provenance_chain)
        result["source"] = self.provider_id
        return result


class WorkloadEvidenceProvider(Protocol):
    provider_id: str
    supported_kinds: tuple[str, ...]

    def resolve(self, name: str, *, allow_live: bool) -> Optional[WorkloadEvidence]:
        ...


class SteamWorkloadProvider:
    provider_id = "steam"
    supported_kinds = ("game",)

    def resolve(self, name: str, *, allow_live: bool) -> Optional[WorkloadEvidence]:
        from src.app.services.connectors.steam_requirements import get_game_requirements

        raw = get_game_requirements(name, allow_live=allow_live)
        if not raw:
            return None
        source = str(raw.get("source") or self.provider_id)
        source_url = str(raw.get("source_url") or "") or None
        source_record_id = str(raw.get("appid") or "") or None
        retrieved_at = str(raw.get("retrieved_at") or "") or None
        provenance = tuple(
            value for value in (
                f"provider:{source}",
                f"url:{source_url}" if source_url else None,
                f"record:{source_record_id}" if source_record_id else None,
                f"retrieved_at:{retrieved_at}" if retrieved_at else None,
            ) if value
        )
        return WorkloadEvidence(
            kind="game",
            requested_name=name,
            resolved_name=str(raw.get("title") or name),
            provider_id=source,
            status="resolved",
            minimum=dict(raw.get("minimum") or {}),
            recommended=dict(raw.get("recommended") or {}),
            source_url=source_url,
            source_record_id=source_record_id,
            retrieved_at=retrieved_at,
            cached=bool(raw.get("cached")),
            confidence=1.0 if source_url and retrieved_at else 0.7,
            provenance_chain=provenance,
            identity_resolution=dict(raw.get("identity_resolution") or {}),
            canonical_title=str(raw.get("title") or name),
            publisher=str(raw.get("publisher") or "") or None,
            app_id=str(raw.get("appid") or "") or None,
            release_state=str(raw.get("release_state") or "") or None,
            release_date=str(raw.get("release_date") or "") or None,
            requirements_completeness=str(raw.get("requirements_completeness") or "") or None,
        )


class WorkloadEvidenceRegistry:
    def __init__(self, providers: Iterable[WorkloadEvidenceProvider] = ()) -> None:
        self._providers = list(providers)

    def register(self, provider: WorkloadEvidenceProvider) -> None:
        if any(item.provider_id == provider.provider_id for item in self._providers):
            raise ValueError(f"duplicate workload provider: {provider.provider_id}")
        self._providers.append(provider)

    def provider_ids_for(self, kind: str) -> tuple[str, ...]:
        """List enrolled providers for a workload kind without implying readiness."""
        normalized = str(kind or "").strip().lower()
        return tuple(
            provider.provider_id
            for provider in self._providers
            if normalized in provider.supported_kinds
        )

    def recognizes_offline(self, name: str) -> bool:
        """Return whether an enrolled provider has bounded local evidence for a name.

        This is a coverage check only. It never enables network access and never
        returns requirements or authorizes a product.
        """
        candidate = str(name or "").strip()
        if not candidate:
            return False
        for provider in self._providers:
            for kind in provider.supported_kinds:
                result, _attempts = self.resolve_with_trace(
                    kind, candidate, allow_live=False,
                )
                if result is not None:
                    return True
        return False

    def resolve(
        self, kind: str, name: str, *, allow_live: bool,
        provider_allowed: Optional[Callable[[str], bool]] = None,
    ) -> Optional[WorkloadEvidence]:
        result, _attempts = self.resolve_with_trace(
            kind, name, allow_live=allow_live, provider_allowed=provider_allowed,
        )
        return result

    def resolve_with_trace(
        self, kind: str, name: str, *, allow_live: bool,
        provider_allowed: Optional[Callable[[str], bool]] = None,
    ) -> tuple[Optional[WorkloadEvidence], list[Dict[str, Any]]]:
        """Resolve evidence and retain a bounded provider-attempt record.

        The record is safe to expose in Decision Trace: it contains provider IDs
        and outcomes, not credentials, prompts, or private model reasoning.
        """
        attempts: list[Dict[str, Any]] = []
        for provider in self._providers:
            if kind not in provider.supported_kinds:
                continue
            if provider_allowed is not None and not provider_allowed(provider.provider_id):
                attempts.append({
                    "provider_id": provider.provider_id,
                    "status": "blocked_by_source_policy",
                    "allow_live": bool(allow_live),
                })
                continue
            try:
                result = provider.resolve(name, allow_live=allow_live)
            except Exception as exc:
                attempts.append({
                    "provider_id": provider.provider_id,
                    "status": "provider_error",
                    "allow_live": bool(allow_live),
                    "error_type": type(exc).__name__,
                })
                continue
            if result is not None:
                attempts.append({
                    "provider_id": provider.provider_id,
                    "status": "resolved",
                    "allow_live": bool(allow_live),
                    "source_record_id": result.source_record_id,
                })
                return result, attempts
            attempts.append({
                "provider_id": provider.provider_id,
                "status": "no_authoritative_result",
                "allow_live": bool(allow_live),
            })
        return None, attempts


def default_registry() -> WorkloadEvidenceRegistry:
    return WorkloadEvidenceRegistry([SteamWorkloadProvider()])
