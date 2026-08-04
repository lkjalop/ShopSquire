"""Scatter-gather silent-hang guard — a hung leg must not block the request.

Was: asyncio.gather(*legs, return_exceptions=True) with NO timeout -> a slow vector DB /
caption LLM / CV leg hangs the whole recommendation forever (silent hang). Now each leg
is wrapped in _bounded() (asyncio.wait_for); a timeout falls back to the leg default and
the rest return within budget, with the timeout surfaced in timings (never silent).
"""
from __future__ import annotations

import asyncio
import pytest

from src.app.services import recommend_pipeline as rp


@pytest.mark.asyncio
async def test_bounded_times_out_and_reraises():
    async def _hang():
        await asyncio.sleep(10)
        return "never"
    with pytest.raises(asyncio.TimeoutError):
        await rp._bounded(_hang(), 0.05, "hang")


@pytest.mark.asyncio
async def test_bounded_passes_through_fast_result():
    async def _fast():
        return [1, 2, 3]
    assert await rp._bounded(_fast(), 1.0, "fast") == [1, 2, 3]


@pytest.mark.asyncio
async def test_hung_leg_falls_back_not_blocks():
    # A hung leg inside gather(return_exceptions=True) becomes a TimeoutError, which the
    # pipeline's _res() maps to the default — so the request completes bounded.
    async def _hang():
        await asyncio.sleep(10)
        return ["should-not-appear"]
    async def _fast():
        return ["db-hit"]

    results = await asyncio.gather(
        rp._bounded(_fast(), 1.0, "db"),
        rp._bounded(_hang(), 0.05, "vector"),
        return_exceptions=True,
    )
    # fast leg succeeded; hung leg is a captured TimeoutError (not raised, not blocking)
    assert results[0] == ["db-hit"]
    assert isinstance(results[1], asyncio.TimeoutError)


def test_timeout_budgets_are_configurable():
    # Budgets read from env (silent-hang guard is tunable per deployment).
    assert rp._LEG_TIMEOUT_S > 0 and rp._CV_TIMEOUT_S > 0 and rp._DEEP_TIMEOUT_S > 0


@pytest.mark.asyncio
async def test_bounded_records_timeout_reason():
    # A timed-out leg is recorded in the errors map (surfaced in trace), not silent.
    errs: dict = {}
    async def _hang():
        await asyncio.sleep(10)
    with pytest.raises(asyncio.TimeoutError):
        await rp._bounded(_hang(), 0.05, "vector", errs)
    assert errs.get("vector", "").startswith("timeout")


@pytest.mark.asyncio
async def test_bounded_records_leg_failure_reason():
    # A non-timeout leg failure (e.g. missing index) is recorded with its type, then re-raised
    # so gather(return_exceptions=True) still falls back to the leg default.
    errs: dict = {}
    async def _boom():
        raise ValueError("vector index not built")
    with pytest.raises(ValueError):
        await rp._bounded(_boom(), 1.0, "caption", errs)
    assert "ValueError" in errs.get("caption", "")
    assert "index not built" in errs.get("caption", "")
