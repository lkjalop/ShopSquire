import threading
import time

import pytest

from src.app.services.local_model_roles import (
    _reset_local_model_scheduler_for_tests,
    execute_local_model_role,
    last_local_model_schedule_metrics,
    local_model_scheduler_snapshot,
)


@pytest.fixture(autouse=True)
def _clean_scheduler(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_MAX_CONCURRENCY", "1")
    _reset_local_model_scheduler_for_tests()
    yield
    _reset_local_model_scheduler_for_tests()


def test_local_role_uses_gateway_and_fixture_artifact_without_commerce_authority():
    text = execute_local_model_role(
        "hello", role="query_planner", purpose="test", prompt_id="test",
        model="qwen3:14b", digest="0" * 64, timeout_s=1,
        max_output_tokens=20, transport=lambda prompt, _deployment, _request: prompt.upper(),
    )
    assert text == "HELLO"


def test_unverified_artifact_fails_before_transport(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "src.app.services.local_model_roles.verify_ollama_artifact",
        lambda **_kwargs: SimpleNamespace(status="mismatch"),
    )
    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return "bad"

    with pytest.raises(RuntimeError, match="model_artifact_mismatch"):
        execute_local_model_role(
            "hello", role="query_planner", purpose="test", prompt_id="test",
            model="qwen3:14b", digest="a" * 64, timeout_s=1,
            max_output_tokens=20, transport=transport,
        )
    assert called is False


def test_active_router_is_admitted_before_optional_narration():
    occupied = threading.Event()
    release = threading.Event()
    order: list[str] = []
    failures: list[BaseException] = []

    def blocking_transport(_prompt, _deployment, request):
        order.append(request.role)
        if request.role == "requirement_extractor":
            occupied.set()
            assert release.wait(timeout=2)
        return request.role

    def run(role: str):
        try:
            execute_local_model_role(
                role, role=role, purpose="priority-test", prompt_id=role,
                model="qwen3:14b", digest="0" * 64, timeout_s=2,
                max_output_tokens=20, transport=blocking_transport,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    holder = threading.Thread(target=run, args=("requirement_extractor",))
    holder.start()
    assert occupied.wait(timeout=1)
    low = threading.Thread(target=run, args=("market_narrator",))
    high = threading.Thread(target=run, args=("recommendation_turn_router",))
    low.start()
    time.sleep(0.03)
    high.start()
    time.sleep(0.03)
    release.set()
    for thread in (holder, low, high):
        thread.join(timeout=3)

    assert failures == []
    assert order == [
        "requirement_extractor", "recommendation_turn_router", "market_narrator",
    ]


def test_queue_time_consumes_total_deadline_and_is_observable():
    occupied = threading.Event()
    release = threading.Event()

    def holding_transport(prompt, _deployment, _request):
        occupied.set()
        release.wait(timeout=1)
        return prompt

    holder = threading.Thread(target=lambda: execute_local_model_role(
        "hold", role="requirement_extractor", purpose="deadline-test",
        prompt_id="hold", model="qwen3:14b", digest="0" * 64,
        timeout_s=1, max_output_tokens=20, transport=holding_transport,
    ))
    holder.start()
    assert occupied.wait(timeout=1)

    with pytest.raises(RuntimeError, match="local_model_queue_timeout"):
        execute_local_model_role(
            "late", role="market_narrator", purpose="deadline-test",
            prompt_id="late", model="qwen3:14b", digest="0" * 64,
            timeout_s=0.05, max_output_tokens=20,
            transport=lambda *_args: "must not run",
        )
    metrics = last_local_model_schedule_metrics()
    assert metrics["status"] == "timed_out"
    assert metrics["failure_code"] == "local_model_queue_timeout"
    assert metrics["queue_ms"] >= 40

    release.set()
    holder.join(timeout=2)
    snapshot = local_model_scheduler_snapshot()
    assert snapshot["policy"] == "local-model-priority-v1"
    assert snapshot["roles"]["market_narrator"]["last_status"] == "timed_out"
