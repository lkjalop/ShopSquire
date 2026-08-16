import asyncio
import threading
import time

from src.app.services import bounded_parser_execution
from src.app.services.bounded_parser_execution import ParserBudget, execute_parser_bounded


def test_parser_completes_with_explicit_budget_projection():
    outcome = asyncio.run(execute_parser_bounded(
        b"requirements",
        lambda: ([{"claim_id": "c1"}], [{"claim_id": "ctx1"}]),
        budget=ParserBudget(max_input_bytes=100, timeout_ms=100, max_claims=4),
    ))

    assert outcome.status == "completed"
    assert [row["claim_id"] for row in outcome.product_claims] == ["c1"]
    assert outcome.projection["input_bytes"] == 12
    assert outcome.projection["candidate_claims"] == 2


def test_oversize_input_is_rejected_before_parser_dispatch():
    called = False

    def parser():
        nonlocal called
        called = True
        return [], []

    outcome = asyncio.run(execute_parser_bounded(
        b"x" * 11, parser,
        budget=ParserBudget(max_input_bytes=10, timeout_ms=100),
    ))

    assert outcome.status == "input_too_large"
    assert outcome.projection["failure_code"] == "source_parser_input_too_large"
    assert called is False


def test_slow_parser_times_out_and_late_result_is_never_accepted():
    def parser():
        time.sleep(0.2)
        return [{"claim_id": "late"}], []

    started = time.perf_counter()
    outcome = asyncio.run(execute_parser_bounded(
        b"small", parser,
        budget=ParserBudget(max_input_bytes=100, timeout_ms=20),
    ))

    assert time.perf_counter() - started < 0.15
    assert outcome.status == "timeout"
    assert outcome.product_claims == ()
    assert outcome.projection["late_result_quarantined"] is True


def test_parser_exception_is_a_typed_failure_not_zero_yield():
    def parser():
        raise ValueError("hostile parser input")

    outcome = asyncio.run(execute_parser_bounded(b"x", parser))

    assert outcome.status == "failed"
    assert outcome.projection["failure_code"] == "source_parser_failed"
    assert outcome.projection["error_type"] == "ValueError"


def test_claim_limit_failure_discards_all_rows():
    outcome = asyncio.run(execute_parser_bounded(
        b"x", lambda: ([{"claim_id": str(i)} for i in range(3)], []),
        budget=ParserBudget(max_claims=2),
    ))

    assert outcome.status == "claim_limit_exceeded"
    assert outcome.product_claims == ()
    assert outcome.projection["failure_code"] == "source_parser_claim_limit_exceeded"


def test_parser_capacity_exhaustion_fails_visible_without_dispatch(monkeypatch):
    slots = threading.BoundedSemaphore(value=1)
    slots.acquire()
    monkeypatch.setattr(bounded_parser_execution, "_PARSER_SLOTS", slots)
    called = False

    def parser():
        nonlocal called
        called = True
        return [], []

    outcome = asyncio.run(execute_parser_bounded(b"x", parser))

    assert outcome.status == "capacity_exhausted"
    assert outcome.projection["failure_code"] == "source_parser_capacity_exhausted"
    assert called is False
