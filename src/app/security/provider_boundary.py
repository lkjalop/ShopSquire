from __future__ import annotations

from typing import Any, Iterable, Tuple

from src.app.policy.data_residency import ResidencyVerdict, check_transfer
from src.app.security.dlp_export import dlp_scrub_all

_LOCAL_PROVIDERS = {"ollama", "ollama_local", "local", "none", "rules"}
_PROVIDER_ALIASES = {
    "openai_chat": "openai",
    "openai_fallback": "openai",
    "api": "openai",
    "local_ollama": "ollama",
}


def normalize_provider_key(provider: str | None) -> str:
    key = str(provider or "").strip().lower()
    return _PROVIDER_ALIASES.get(key, key)


def require_provider_transfer(
    provider: str | None,
    *,
    data_categories: Iterable[str] | None = None,
) -> ResidencyVerdict:
    verdict = check_transfer(
        normalize_provider_key(provider),
        data_categories=list(data_categories or []),
    )
    verdict.assert_allowed()
    return verdict


def sanitize_for_provider(
    provider: str | None,
    payload: Any,
    *,
    data_categories: Iterable[str] | None = None,
) -> Tuple[Any, int, ResidencyVerdict]:
    verdict = require_provider_transfer(provider, data_categories=data_categories)
    if verdict.provider in _LOCAL_PROVIDERS:
        return payload, 0, verdict
    scrubbed, hits = _scrub_value(payload)
    return scrubbed, hits, verdict


def _scrub_value(value: Any) -> Tuple[Any, int]:
    if isinstance(value, str):
        scrubbed, hits = dlp_scrub_all(value)
        return scrubbed, hits
    if isinstance(value, dict):
        out = {}
        total = 0
        for key, item in value.items():
            scrubbed, hits = _scrub_value(item)
            out[key] = scrubbed
            total += hits
        return out, total
    if isinstance(value, list):
        out = []
        total = 0
        for item in value:
            scrubbed, hits = _scrub_value(item)
            out.append(scrubbed)
            total += hits
        return out, total
    if isinstance(value, tuple):
        items = []
        total = 0
        for item in value:
            scrubbed, hits = _scrub_value(item)
            items.append(scrubbed)
            total += hits
        return tuple(items), total
    return value, 0
