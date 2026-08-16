"""Bounded execution for untrusted document parsers.

Transport limits are not parser limits: a document can be small enough to fetch
yet still trigger expensive parsing.  This boundary keeps the buyer request
responsive, discards late parser results, and returns an honest typed projection
instead of turning parser failure into "no requirements found".
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal


ParserRows = tuple[list[dict[str, Any]], list[dict[str, Any]]]
_PARSER_SLOTS = threading.BoundedSemaphore(value=4)


@dataclass(frozen=True)
class ParserBudget:
    max_input_bytes: int = 2 * 1024 * 1024
    timeout_ms: int = 1_000
    max_claims: int = 128

    def normalized(self) -> "ParserBudget":
        return ParserBudget(
            max_input_bytes=max(1, min(int(self.max_input_bytes), 8 * 1024 * 1024)),
            timeout_ms=max(10, min(int(self.timeout_ms), 10_000)),
            max_claims=max(1, min(int(self.max_claims), 1_024)),
        )


@dataclass(frozen=True)
class ParserExecutionOutcome:
    status: Literal[
        "completed", "input_too_large", "timeout", "cancelled",
        "capacity_exhausted", "claim_limit_exceeded", "failed",
    ]
    product_claims: tuple[dict[str, Any], ...]
    context_claims: tuple[dict[str, Any], ...]
    projection: dict[str, Any]


async def execute_parser_bounded(
    content: bytes,
    parser: Callable[[], ParserRows],
    *,
    budget: ParserBudget | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> ParserExecutionOutcome:
    """Run a parser on a daemon worker and quarantine any late result.

    CPython cannot safely terminate an already-running parser thread.  The input
    size bound limits work, the request stops waiting at the deadline, and a late
    result is never accepted into the evidence ledger.
    """

    configured = (budget or ParserBudget()).normalized()
    input_bytes = len(content)
    base = {
        "input_bytes": input_bytes,
        "max_input_bytes": configured.max_input_bytes,
        "timeout_ms": configured.timeout_ms,
        "max_claims": configured.max_claims,
        "elapsed_ms": 0.0,
        "late_result_quarantined": False,
        "failure_code": None,
        "error_type": None,
    }
    if input_bytes > configured.max_input_bytes:
        return ParserExecutionOutcome(
            status="input_too_large", product_claims=(), context_claims=(),
            projection={
                **base,
                "status": "input_too_large",
                "failure_code": "source_parser_input_too_large",
            },
        )
    if cancellation_requested and cancellation_requested():
        return ParserExecutionOutcome(
            status="cancelled", product_claims=(), context_claims=(),
            projection={
                **base,
                "status": "cancelled",
                "failure_code": "source_parser_cancelled",
            },
        )
    if not _PARSER_SLOTS.acquire(blocking=False):
        return ParserExecutionOutcome(
            status="capacity_exhausted", product_claims=(), context_claims=(),
            projection={
                **base,
                "status": "capacity_exhausted",
                "failure_code": "source_parser_capacity_exhausted",
            },
        )

    result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result.put_nowait(("value", parser()))
        except BaseException as exc:  # keep worker failure outside the request task
            try:
                result.put_nowait(("error", exc))
            except queue.Full:
                pass
        finally:
            _PARSER_SLOTS.release()

    started = time.monotonic()
    worker = threading.Thread(
        target=run,
        name="shopsquire-official-parser",
        daemon=True,
    )
    try:
        worker.start()
    except BaseException:
        _PARSER_SLOTS.release()
        raise
    deadline = started + (configured.timeout_ms / 1_000.0)
    while True:
        elapsed_ms = round((time.monotonic() - started) * 1_000, 3)
        if cancellation_requested and cancellation_requested():
            return ParserExecutionOutcome(
                status="cancelled", product_claims=(), context_claims=(),
                projection={
                    **base,
                    "status": "cancelled",
                    "elapsed_ms": elapsed_ms,
                    "late_result_quarantined": worker.is_alive(),
                    "failure_code": "source_parser_cancelled",
                },
            )
        try:
            kind, value = result.get_nowait()
        except queue.Empty:
            if time.monotonic() >= deadline:
                return ParserExecutionOutcome(
                    status="timeout", product_claims=(), context_claims=(),
                    projection={
                        **base,
                        "status": "timeout",
                        "elapsed_ms": elapsed_ms,
                        "late_result_quarantined": worker.is_alive(),
                        "failure_code": "source_parser_timeout",
                    },
                )
            await asyncio.sleep(0.005)
            continue

        if kind == "error":
            return ParserExecutionOutcome(
                status="failed", product_claims=(), context_claims=(),
                projection={
                    **base,
                    "status": "failed",
                    "elapsed_ms": elapsed_ms,
                    "failure_code": "source_parser_failed",
                    "error_type": type(value).__name__,
                },
            )
        try:
            product_rows, context_rows = value
            product = tuple(dict(row) for row in product_rows)
            context = tuple(dict(row) for row in context_rows)
        except Exception as exc:
            return ParserExecutionOutcome(
                status="failed", product_claims=(), context_claims=(),
                projection={
                    **base,
                    "status": "failed",
                    "elapsed_ms": elapsed_ms,
                    "failure_code": "source_parser_invalid_result",
                    "error_type": type(exc).__name__,
                },
            )
        if len(product) + len(context) > configured.max_claims:
            return ParserExecutionOutcome(
                status="claim_limit_exceeded", product_claims=(), context_claims=(),
                projection={
                    **base,
                    "status": "claim_limit_exceeded",
                    "elapsed_ms": elapsed_ms,
                    "failure_code": "source_parser_claim_limit_exceeded",
                },
            )
        return ParserExecutionOutcome(
            status="completed", product_claims=product, context_claims=context,
            projection={
                **base,
                "status": "completed",
                "elapsed_ms": elapsed_ms,
                "candidate_claims": len(product) + len(context),
            },
        )


__all__ = ["ParserBudget", "ParserExecutionOutcome", "execute_parser_bounded"]
