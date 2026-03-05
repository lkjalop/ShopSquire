"""Chaos-test conftest — per-test state isolation and OOM guards.

Each chaos test manipulates ``app.state`` fields (``chaos_error_prob``,
``max_concurrency``, ``rate_limit_per_min``, etc.) and may start a
``webhook_dispatcher`` background thread.  The tests already have try/finally
blocks for the happy path, but if a test crashes *before* reaching its
finally block (e.g. during monkeypatch setup or in a sub-call), the shared
singleton ``app.state`` is left dirty and poisons all following tests.

This autouse fixture provides a second, unconditional safety layer:

1. Snapshots all mutable chaos-related ``app.state`` fields before the test.
2. Restores them in teardown regardless of whether the test passed or raised.
3. Calls ``webhook_dispatcher.stop_worker()`` if a worker thread was leaked.
4. Emits a stderr OOM warning (200 MB threshold) using psutil.

The root-conftest ``_rss_guard`` fixture still fires for chaos tests too
(300 MB threshold); these two work together, not in conflict.
"""
from __future__ import annotations

import os
import sys

import pytest

# All app.state fields that chaos tests are known to mutate.
_CHAOS_STATE_FIELDS = (
    "chaos_error_prob",
    "chaos_error_prefixes",
    "max_concurrency",
    "rate_limit_per_min",
    "rate_limit_window_sec",
)

# Sentinel so we can distinguish "field was absent" from "field was 0/None/[]".
_UNSET = object()


@pytest.fixture(autouse=True)
def _chaos_state_restore():
    """Unconditionally restore chaos app.state and threads after every chaos test."""
    import src.app.services.webhook_dispatcher as _wd  # noqa: PLC0415
    from src.app.main import create_app  # noqa: PLC0415

    app = create_app()

    # ── PRE-TEST: snapshot ────────────────────────────────────────────────────
    snapshots: dict[str, object] = {
        f: getattr(app.state, f, _UNSET) for f in _CHAOS_STATE_FIELDS
    }

    rss_before: int = 0
    try:
        import psutil  # noqa: PLC0415
        rss_before = psutil.Process(os.getpid()).memory_info().rss
    except Exception:
        pass

    yield  # ← test body runs here

    # ── POST-TEST: restore ────────────────────────────────────────────────────

    # 1. Restore every chaos app.state field to its pre-test value.
    for field, val in snapshots.items():
        if val is not _UNSET:
            try:
                setattr(app.state, field, val)
            except Exception:
                pass

    # 2. Stop any webhook_dispatcher worker thread that the test left running.
    #    Tests call start_worker() + stop_worker() in a try/finally, but if the
    #    test crashes before stop_worker() the thread keeps polling indefinitely,
    #    leaking a descriptor + minor CPU.
    try:
        if _wd._worker_thread and _wd._worker_thread.is_alive():
            _wd.stop_worker()
    except Exception:
        pass

    # 3. RSS delta warning (lower threshold than root conftest — chaos tests
    #    are the most likely source of large interim allocations).
    if rss_before:
        try:
            import psutil  # noqa: PLC0415
            rss_after = psutil.Process(os.getpid()).memory_info().rss
            delta_mb = (rss_after - rss_before) / 1_048_576
            if delta_mb > 200:
                sys.stderr.write(
                    f"\n[CHAOS-OOM] Chaos test grew RSS by {delta_mb:.0f} MB "
                    f"(before={rss_before // 1_048_576} MB, "
                    f"after={rss_after // 1_048_576} MB). "
                    "Investigate: ML model load, engine leak, or unclosed "
                    "start_worker() call.\n"
                )
        except Exception:
            pass
