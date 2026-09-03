"""Measured local-model latency profiles used by bounded model roles."""
from __future__ import annotations

import math
from typing import Any, Iterable

from sqlalchemy import text


def percentile(values: Iterable[int], percentile_value: float) -> int | None:
    rows = sorted(max(0, int(value)) for value in values)
    if not rows:
        return None
    rank = max(0, min(len(rows) - 1, math.ceil(percentile_value * len(rows)) - 1))
    return rows[rank]


def observed_model_latency_ms(
    *, prompt_id: str = "recommend-router-v2", sample_size: int = 32,
) -> int | None:
    """Return p90 accepted-to-terminal wall time from the durable model ledger."""

    profile = model_latency_profile(prompt_id=prompt_id, sample_size=sample_size)
    return profile.get("p90_ms")


def model_latency_profile(
    *, prompt_id: str, sample_size: int = 32,
) -> dict[str, Any]:
    """Measured terminal latency and last successful full-contract execution."""

    try:
        from src.app.models.db import get_engine

        with get_engine().connect() as connection:
            rows = connection.execute(text("""
                SELECT run_id, event_type, occurred_at_ms
                FROM agent_run_event
                WHERE prompt_id = :prompt_id
                  AND event_type IN ('accepted', 'completed', 'timeout', 'failed')
                ORDER BY occurred_at_ms DESC
                LIMIT :row_limit
            """), {
                "prompt_id": prompt_id,
                "row_limit": max(8, min(int(sample_size), 128)) * 2,
            }).mappings().all()
    except Exception:
        return {
            "prompt_id": prompt_id, "sample_count": 0, "p50_ms": None,
            "p90_ms": None, "last_success_at_ms": None,
        }
    starts: dict[str, int] = {}
    terminals: dict[str, int] = {}
    for row in rows:
        run_id = str(row["run_id"])
        stamp = int(row["occurred_at_ms"])
        if row["event_type"] == "accepted":
            starts[run_id] = stamp
        else:
            terminals.setdefault(run_id, stamp)
    durations = [
        terminals[run_id] - started
        for run_id, started in starts.items()
        if run_id in terminals and terminals[run_id] >= started
    ]
    bounded = durations[:sample_size]
    successful = [
        int(row["occurred_at_ms"]) for row in rows if row["event_type"] == "completed"
    ]
    return {
        "prompt_id": prompt_id,
        "sample_count": len(bounded),
        "p50_ms": percentile(bounded, 0.50),
        "p90_ms": percentile(bounded, 0.90),
        "last_success_at_ms": max(successful) if successful else None,
    }


__all__ = ["model_latency_profile", "observed_model_latency_ms", "percentile"]
