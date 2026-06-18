"""Observable partial-failure wrapper — make swallowed stage errors VISIBLE.

The silent `except Exception: pass` class is what hid the ASUS grounding bug for hours: a stage
failed, returned nothing, and the request silently fell back to generic with no signal anywhere
(not in the response, not in the decision trace). `safe_stage` runs a stage closure and, on
failure, emits a decision-trace event (`stage_partial_failure`) AND a warning log, then returns the
caller's default — so a degraded recommendation is AUDITABLE, not invisible.

Use it to replace bare `try/except Exception: pass` (or `: return default`) on non-fatal stages
(retrieval, image grounding, price fallback, NQE, narration, finalizer). The boundary is still
non-fatal — the request continues — but the failure is now recorded against the trace.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TypeVar

_log = logging.getLogger(__name__)
T = TypeVar("T")


def safe_stage(
    stage: str,
    fn: Callable[[], T],
    *,
    default: Optional[T] = None,
    trace_id: str | None = None,
    severity: str = "warn",
    extra: Optional[dict[str, Any]] = None,
) -> Optional[T]:
    """Run ``fn()``; on any exception record a trace event + log and return ``default``.

    ``stage`` is the human-readable stage name (e.g. "image_grounding", "price_fallback") — it
    becomes the trace source_id so the partial failure is attributable. ``trace_id`` ties the
    event to the request's decision trace; without it the event is dropped (log still fires)."""
    try:
        return fn()
    except Exception as exc:  # deliberate boundary: failure is RECORDED below, never swallowed
        payload: dict[str, Any] = {
            "stage": stage,
            "error": f"{type(exc).__name__}: {exc}",
            "severity": severity,
            "degraded": True,
        }
        if extra:
            try:
                payload.update(extra)
            except Exception:
                pass
        try:
            from src.app.services.decision_log import log_trace_event
            log_trace_event(
                trace_id, "stage_partial_failure", "system", stage, "system", None, payload,
            )
        except Exception:
            # The observability sink itself must never break the request — the single
            # acceptable silent boundary in the codebase (it IS the recorder).
            pass
        _log.warning("stage_partial_failure stage=%s error=%s", stage, exc, exc_info=False)
        return default
