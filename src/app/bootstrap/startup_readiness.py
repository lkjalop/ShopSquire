"""Typed startup capability truth for required and optional runtime services."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, TypeVar

from fastapi import FastAPI

T = TypeVar("T")


@dataclass(frozen=True)
class StartupCapabilityResult:
    name: str
    criticality: Literal["required", "optional"]
    phase: Literal["start", "stop"]
    status: Literal["ready", "degraded", "failed", "stopped"]
    observed_at: str
    error_type: str | None = None


def _record(app: FastAPI, result: StartupCapabilityResult) -> None:
    current = dict(getattr(app.state, "startup_capabilities", {}) or {})
    current[result.name] = asdict(result)
    app.state.startup_capabilities = current
    try:
        from src.app.observability.metrics import (
            startup_capability_failures_total, startup_capability_status,
        )
        startup_capability_status.labels(
            capability=result.name, criticality=result.criticality,
        ).set(1 if result.status in {"ready", "stopped"} else 0)
        if result.status in {"degraded", "failed"}:
            startup_capability_failures_total.labels(
                capability=result.name, criticality=result.criticality,
                phase=result.phase, error_type=result.error_type or "unknown",
            ).inc()
    except Exception:
        # Metrics must not alter the capability result that they describe.
        return


def run_startup_step(
    app: FastAPI, *, name: str, criticality: Literal["required", "optional"],
    operation: Callable[[], T],
) -> T | None:
    """Run a classified startup operation and preserve its observable truth."""
    try:
        value = operation()
    except Exception as exc:
        status = "failed" if criticality == "required" else "degraded"
        _record(app, StartupCapabilityResult(
            name=name, criticality=criticality, phase="start", status=status,
            observed_at=datetime.now(timezone.utc).isoformat(),
            error_type=type(exc).__name__,
        ))
        if criticality == "required":
            raise
        return None
    _record(app, StartupCapabilityResult(
        name=name, criticality=criticality, phase="start", status="ready",
        observed_at=datetime.now(timezone.utc).isoformat(),
    ))
    return value


def record_shutdown_result(
    app: FastAPI, *, name: str, criticality: Literal["required", "optional"],
    error: Exception | None = None,
) -> None:
    _record(app, StartupCapabilityResult(
        name=name, criticality=criticality, phase="stop",
        status="failed" if error and criticality == "required" else "degraded" if error else "stopped",
        observed_at=datetime.now(timezone.utc).isoformat(),
        error_type=type(error).__name__ if error else None,
    ))


__all__ = ["StartupCapabilityResult", "record_shutdown_result", "run_startup_step"]
