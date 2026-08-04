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
        )


class WorkloadEvidenceRegistry:
    def __init__(self, providers: Iterable[WorkloadEvidenceProvider] = ()) -> None:
        self._providers = list(providers)

    def register(self, provider: WorkloadEvidenceProvider) -> None:
        if any(item.provider_id == provider.provider_id for item in self._providers):
            raise ValueError(f"duplicate workload provider: {provider.provider_id}")
        self._providers.append(provider)

    def resolve(
        self, kind: str, name: str, *, allow_live: bool,
        provider_allowed: Optional[Callable[[str], bool]] = None,
    ) -> Optional[WorkloadEvidence]:
        for provider in self._providers:
            if kind not in provider.supported_kinds:
                continue
            if provider_allowed is not None and not provider_allowed(provider.provider_id):
                continue
            result = provider.resolve(name, allow_live=allow_live)
            if result is not None:
                return result
        return None


def default_registry() -> WorkloadEvidenceRegistry:
    return WorkloadEvidenceRegistry([SteamWorkloadProvider()])
