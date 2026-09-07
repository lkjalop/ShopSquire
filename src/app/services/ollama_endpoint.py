"""Canonical local Ollama endpoint helpers."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_ollama_url(value: str) -> str:
    """Avoid Windows trying IPv6 first when Ollama is bound to IPv4 loopback."""

    raw = str(value or "http://127.0.0.1:11434").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.hostname != "localhost":
        return raw
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(
        (parsed.scheme, f"127.0.0.1{port}", parsed.path, parsed.query, parsed.fragment)
    ).rstrip("/")


__all__ = ["normalize_ollama_url"]
