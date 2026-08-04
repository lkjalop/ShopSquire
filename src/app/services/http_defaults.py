"""Shared outbound-HTTP timeout default (agnostic infra).

A network call with no timeout can hang a worker or request thread indefinitely on a slow/dead endpoint —
a silent hang. Every outbound `requests`/`httpx` call must pass an explicit timeout; this is the single
env-configurable default they share, so ops can tune it without code changes. The companion ratchet
(tests/test_no_untimed_outbound_http.py) keeps new calls from regressing.
"""
from __future__ import annotations

import os

_DEFAULT = 10.0


def outbound_timeout(default: float = _DEFAULT) -> float:
    try:
        v = float(os.getenv("OUTBOUND_HTTP_TIMEOUT_SEC", default) or default)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


# Module-level constant for the common case (call sites that don't need per-request tuning).
DEFAULT_OUTBOUND_TIMEOUT = outbound_timeout()
