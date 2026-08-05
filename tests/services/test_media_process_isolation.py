from __future__ import annotations

import os

from src.app.services.media_process_isolation import run_isolated_media_call


_FIXTURE = "tests.services.media_isolation_fixture"


def test_media_call_runs_in_separate_process():
    result = run_isolated_media_call(
        module_name=_FIXTURE, function_name="echo", kwargs={"value": "ok"}, timeout_s=3,
    )
    assert result.status == "completed"
    assert result.value["value"] == "ok"
    assert result.value["pid"] != os.getpid()


def test_media_timeout_terminates_worker_without_late_result():
    result = run_isolated_media_call(
        module_name=_FIXTURE, function_name="wait", kwargs={"seconds": 5}, timeout_s=0.1,
    )
    assert result.status == "timed_out"
    assert result.value is None


def test_media_failure_is_typed():
    result = run_isolated_media_call(
        module_name=_FIXTURE, function_name="fail", kwargs={}, timeout_s=3,
    )
    assert result.status == "failed"
    assert "ValueError" in str(result.error)
