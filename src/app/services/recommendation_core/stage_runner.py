"""Shared execution boundary for typed recommendation stages."""
from __future__ import annotations

import logging
import time
from copy import copy, deepcopy
from typing import Any, Callable


def run_guarded_stage(
    response: Any, name: str, operation: Callable[[], None], *,
    cancellation: Any = None, logger: logging.Logger | None = None,
    input_artifact_refs: tuple[str, ...] = (),
    output_artifact_refs: tuple[str, ...] = (),
    dependency_stage_ids: tuple[str, ...] = (),
    stage_id: str | None = None,
    isolated: bool = False,
) -> str:
    """Execute one additive stage without allowing it to corrupt a valid shelf."""
    log = logger or logging.getLogger("shopsquire.recommendation.stage")
    started = time.perf_counter()
    priority_before = response._msg_priority
    # Only stage-owned response output is copied. The request envelope may own
    # cancellation tokens/locks; it is a read-only input, not rollback state.
    owned = {key: deepcopy(value) for key, value in vars(response).items()
             if key not in {'envelope', 'record_stage'}}
    candidate = copy(response) if isolated else response
    if isolated:
        vars(candidate).update(deepcopy(owned))
    status = "ok"
    try:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        operation(candidate) if isolated else operation()
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if isolated:
            vars(response).update({key: value for key, value in vars(candidate).items()
                                   if key not in {'envelope', 'record_stage'}})
    except Exception as exc:
        for key in list(vars(response)):
            if key not in {'envelope', 'record_stage'} and key not in owned:
                delattr(response, key)
        vars(response).update(owned)
        from src.app.services.recommendation_core.cancellation import RecommendationCancelled
        if isinstance(exc, RecommendationCancelled):
            raise
        status = "error"
        log.warning("%s stage skipped: %s", name, repr(exc)[:120])
    response.record_stage(
        name, status=status, latency_ms=(time.perf_counter() - started) * 1000.0,
        stage_id=stage_id,
        won_message=response._msg_priority > priority_before,
        input_artifact_refs=input_artifact_refs,
        output_artifact_refs=output_artifact_refs if status == 'ok' else (),
        dependency_stage_ids=dependency_stage_ids,
    )
    return status


__all__ = ["run_guarded_stage"]
