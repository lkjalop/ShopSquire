from __future__ import annotations

import pytest

from src.app.workers import task_runner


class _Redis:
    def __init__(self, *, fail_xadd: bool = False) -> None:
        self.acked: list[tuple] = []
        self.added: list[tuple[str, dict]] = []
        self.fail_xadd = fail_xadd

    def xack(self, *args):
        self.acked.append(args)
        return 1

    def xadd(self, stream, fields, **_kwargs):
        if self.fail_xadd:
            raise RuntimeError("redis unavailable")
        self.added.append((stream, fields))
        return "2-0"


class _ClaimRedis(_Redis):
    def xautoclaim(self, *args, **kwargs):
        del args, kwargs
        return [
            "0-0",
            [
                (
                    "7-0",
                    {
                        "task_name": "recovered",
                        "task_id": "task-7",
                        "payload": '{"replayed": true}',
                    },
                )
            ],
            [],
        ]


def test_decoded_redis_fields_execute_and_ack() -> None:
    seen = []
    redis = _Redis()
    task_runner._HANDLERS["decoded"] = lambda payload: seen.append(payload)
    try:
        task_runner._process_message(
            "1-0",
            {
                "task_name": "decoded",
                "task_id": "task-1",
                "payload": '{"value": 7}',
            },
            redis,
        )
    finally:
        task_runner._HANDLERS.pop("decoded", None)

    assert seen == [{"value": 7}]
    assert len(redis.acked) == 1
    assert redis.added == []


def test_failed_task_is_requeued_before_ack(monkeypatch) -> None:
    redis = _Redis()
    monkeypatch.setenv("TASK_MAX_ATTEMPTS", "3")
    task_runner._HANDLERS["fails"] = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("boom")
    )
    try:
        task_runner._process_message(
            "1-0",
            {
                "task_name": "fails",
                "task_id": "task-1",
                "payload": "{}",
                "attempts": "0",
            },
            redis,
        )
    finally:
        task_runner._HANDLERS.pop("fails", None)

    assert redis.added[0][0] == task_runner.STREAM_NAME
    assert redis.added[0][1]["attempts"] == 1
    assert len(redis.acked) == 1


def test_terminal_failure_and_unknown_task_are_dead_lettered(monkeypatch) -> None:
    redis = _Redis()
    monkeypatch.setenv("TASK_MAX_ATTEMPTS", "2")
    task_runner._HANDLERS["fails"] = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("boom")
    )
    try:
        task_runner._process_message(
            "1-0",
            {
                "task_name": "fails",
                "task_id": "task-1",
                "payload": "{}",
                "attempts": "1",
            },
            redis,
        )
    finally:
        task_runner._HANDLERS.pop("fails", None)
    task_runner._process_message(
        "2-0",
        {"task_name": "missing", "task_id": "task-2", "payload": "{}"},
        redis,
    )

    assert [entry[0] for entry in redis.added] == [
        task_runner.DEAD_LETTER_STREAM,
        task_runner.DEAD_LETTER_STREAM,
    ]
    assert len(redis.acked) == 2


def test_requeue_failure_leaves_original_pending(monkeypatch) -> None:
    redis = _Redis(fail_xadd=True)
    monkeypatch.setenv("TASK_MAX_ATTEMPTS", "3")
    task_runner._HANDLERS["fails"] = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("boom")
    )
    try:
        task_runner._process_message(
            "1-0",
            {"task_name": "fails", "task_id": "task-1", "payload": "{}"},
            redis,
        )
    finally:
        task_runner._HANDLERS.pop("fails", None)

    assert redis.acked == []


def test_stale_pending_task_is_reclaimed_and_processed(monkeypatch) -> None:
    seen = []
    redis = _ClaimRedis()
    monkeypatch.setenv("TASK_PENDING_MIN_IDLE_MS", "1000")
    task_runner._HANDLERS["recovered"] = lambda payload: seen.append(payload)
    try:
        assert task_runner._recover_pending(redis) == 1
    finally:
        task_runner._HANDLERS.pop("recovered", None)

    assert seen == [{"replayed": True}]
    assert redis.acked[0][-1] == "7-0"


def test_production_does_not_silently_fallback_without_redis(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TASK_ALLOW_INPROCESS_FALLBACK", raising=False)
    monkeypatch.setattr(task_runner, "_get_redis", lambda: None)

    with pytest.raises(RuntimeError, match="durable_task_backend_unavailable"):
        task_runner.submit_task("important", {})


def test_local_fallback_remains_explicitly_available(monkeypatch) -> None:
    submitted = []
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("TASK_ALLOW_INPROCESS_FALLBACK", raising=False)
    monkeypatch.setattr(task_runner, "_get_redis", lambda: None)
    monkeypatch.setattr(
        task_runner,
        "_execute_in_fallback_pool",
        lambda task_name, payload, task_id: submitted.append(
            (task_name, payload, task_id)
        ),
    )

    task_id = task_runner.submit_task("local-task", {"safe": True})
    assert submitted == [("local-task", {"safe": True}, task_id)]
