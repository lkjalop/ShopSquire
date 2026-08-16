"""Verify an enrolled model artifact against the local Ollama daemon.

The configured digest is a policy expectation, not proof.  This module compares
it with Ollama's manifest digest before a deployment can enter the execution
gateway.  It intentionally records no model template or parameters.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

import requests


_DIGEST = re.compile(r"^(?:sha256:)?([a-fA-F0-9]{64})$")
_CACHE_LOCK = threading.Lock()
_VERIFIED_CACHE: dict[tuple[str, str, str], tuple[float, "OllamaArtifactVerification"]] = {}


@dataclass(frozen=True)
class OllamaArtifactVerification:
    status: Literal["verified", "missing", "mismatch", "unavailable", "invalid_expected_digest"]
    model: str
    expected_digest: str
    observed_digest: str | None
    endpoint_identity: str
    observed_at: str
    error_code: str | None = None


FetchTags = Callable[[str, float], dict[str, Any]]


def _default_fetch(url: str, timeout_s: float) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout_s)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


def verify_ollama_artifact(
    *,
    base_url: str,
    model: str,
    expected_digest: str,
    timeout_s: float = 2.0,
    fetch_tags: FetchTags | None = None,
) -> OllamaArtifactVerification:
    parsed = urlsplit(base_url)
    endpoint_identity = str(parsed.hostname or "")
    observed_at = datetime.now(UTC).isoformat()
    match = _DIGEST.fullmatch(str(expected_digest or "").strip())
    if not match:
        return OllamaArtifactVerification(
            "invalid_expected_digest", model, str(expected_digest), None,
            endpoint_identity, observed_at, "expected_digest_invalid",
        )
    expected = match.group(1).lower()
    cache_key = (base_url.rstrip("/"), model, expected)
    if fetch_tags is None:
        with _CACHE_LOCK:
            cached = _VERIFIED_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < 60.0:
            return cached[1]
    try:
        payload = (fetch_tags or _default_fetch)(
            base_url.rstrip("/") + "/api/tags", max(0.1, min(timeout_s, 5.0)),
        )
    except Exception as exc:
        return OllamaArtifactVerification(
            "unavailable", model, expected, None, endpoint_identity, observed_at,
            f"ollama_manifest_unavailable:{type(exc).__name__}",
        )
    for row in payload.get("models") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or row.get("model") or "") != model:
            continue
        observed_match = _DIGEST.fullmatch(str(row.get("digest") or "").strip())
        observed = observed_match.group(1).lower() if observed_match else None
        receipt = OllamaArtifactVerification(
            "verified" if observed == expected else "mismatch",
            model, expected, observed, endpoint_identity, observed_at,
            None if observed == expected else "ollama_manifest_digest_mismatch",
        )
        if receipt.status == "verified" and fetch_tags is None:
            with _CACHE_LOCK:
                _VERIFIED_CACHE[cache_key] = (time.monotonic(), receipt)
        return receipt
    return OllamaArtifactVerification(
        "missing", model, expected, None, endpoint_identity, observed_at,
        "ollama_model_not_installed",
    )


__all__ = ["OllamaArtifactVerification", "verify_ollama_artifact"]
