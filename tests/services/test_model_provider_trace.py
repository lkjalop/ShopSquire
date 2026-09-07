from __future__ import annotations

from src.app.services import llm_providers
from src.app.services.recommendation_core.turn_router import router_runtime_contract


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "grounded answer"}}]}


class _OllamaResponse:
    @staticmethod
    def raise_for_status() -> None:
        return None

    @staticmethod
    def json():
        return {"response": '{"desired_outcome":"test"}'}


class _TruncatedOllamaResponse:
    status_code = 200

    @staticmethod
    def json():
        return {
            "response": '{"lane":"SEARCH"',
            "done_reason": "length",
            "eval_count": 320,
        }


def test_azure_foundry_adapter_emits_version_trace(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENDPOINT", "https://foundry.example")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_DEPLOYMENT", "grounded-small")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-only")
    monkeypatch.setattr(
        llm_providers,
        "sanitize_for_provider",
        lambda provider, prompt, data_categories: (prompt, 0, object()),
    )
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: _Response())

    result = llm_providers.AzureFoundryProvider().generate(
        "hello",
        model_version="weights-7",
        prompt_version="buyer-summary-3",
        policy_version="bounded-autonomy-4",
    )

    assert result["text"] == "grounded answer"
    assert result["model"] == "grounded-small"
    assert result["model_version"] == "weights-7"
    assert result["prompt_version"] == "buyer-summary-3"
    assert result["policy_version"] == "bounded-autonomy-4"


def test_version_trace_has_explicit_unversioned_states(monkeypatch) -> None:
    for name in ("MODEL_VERSION", "PROMPT_VERSION", "POLICY_VERSION"):
        monkeypatch.delenv(name, raising=False)
    trace = llm_providers.invocation_version_trace("ollama", "local-model", {})
    assert trace == {
        "provider": "ollama",
        "model": "local-model",
        "model_version": "local-model",
        "prompt_version": "unversioned",
        "policy_version": "unversioned",
    }


def test_ollama_structured_contract_forwards_json_format_and_disables_thinking(monkeypatch) -> None:
    captured = {}

    def post(_url, *, json, timeout):
        captured.update({"payload": json, "timeout": timeout})
        return _OllamaResponse()

    monkeypatch.setattr("requests.post", post)
    result = llm_providers.OllamaProvider().generate(
        "return json",
        model="qwen3:14b",
        format="json",
        think=False,
        timeout_s=17,
    )

    assert result["text"] == '{"desired_outcome":"test"}'
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["think"] is False
    assert captured["timeout"] == 17.0


def test_router_budget_separates_queue_wait_from_inference(monkeypatch) -> None:
    monkeypatch.setenv("ROUTER_TIMEOUT_SEC", "9")
    monkeypatch.setenv("ROUTER_QUEUE_TIMEOUT_SEC", "0.2")

    contract = router_runtime_contract()

    assert contract["inference_timeout_s"] == 9.0
    assert contract["queue_timeout_s"] == 0.2
    assert contract["queue_timeout_s"] < contract["inference_timeout_s"]
    assert contract["late_results_accepted"] is False


def test_disabled_router_model_returns_without_waiting(monkeypatch) -> None:
    from src.app.services.recommendation_core import turn_router

    monkeypatch.setenv("ROUTER_MODEL_ENABLED", "0")
    started = __import__("time").monotonic()
    assert turn_router._default_llm_fn("classify", 12.0) == ""
    assert __import__("time").monotonic() - started < 0.1
    assert turn_router.last_router_call_metrics()["outcome"] == "disabled"


def test_router_receipt_includes_priority_scheduler_timing(monkeypatch) -> None:
    import threading

    from src.app.services.local_model_roles import _reset_local_model_scheduler_for_tests
    from src.app.services.recommendation_core.router_model_call import execute_router_model

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "response": '{"lane":"SEARCH"}',
                "total_duration": 2_000_000,
                "prompt_eval_duration": 1_000_000,
                "eval_duration": 500_000,
            }

    monkeypatch.setenv("ROUTER_MODEL_ENABLED", "1")
    _reset_local_model_scheduler_for_tests()
    rendered, metrics = execute_router_model(
        "route this", 2.0, model="qwen3:14b",
        http_post=lambda *_args, **_kwargs: Response(),
        injected_transport=True,
        gate=threading.BoundedSemaphore(1),
        runtime_contract={"queue_timeout_s": 0.2},
    )

    assert rendered == '{"lane":"SEARCH"}'
    assert metrics["scheduler_role"] == "recommendation_turn_router"
    assert metrics["scheduler_priority"] == 0
    assert metrics["scheduler_status"] == "completed"
    assert metrics["scheduler_queue_ms"] >= 0
    assert metrics["scheduler_execution_ms"] >= 0
    assert metrics["scheduler_cancelled"] is False


def test_router_uses_capacity_for_full_contract_and_records_completion_reason(monkeypatch) -> None:
    import threading

    from src.app.services.local_model_roles import _reset_local_model_scheduler_for_tests
    from src.app.services.recommendation_core.router_model_call import execute_router_model

    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"response": '{"lane":"SEARCH"}', "done_reason": "stop"}

    def post(*_args, **kwargs):
        captured.update(kwargs["json"])
        return Response()

    monkeypatch.delenv("ROUTER_NUM_PREDICT", raising=False)
    monkeypatch.setenv("ROUTER_MODEL_ENABLED", "1")
    _reset_local_model_scheduler_for_tests()
    rendered, metrics = execute_router_model(
        "route this", 2.0, model="qwen3:14b", http_post=post,
        injected_transport=True, gate=threading.BoundedSemaphore(1),
        runtime_contract={"queue_timeout_s": 0.2},
    )

    assert rendered == '{"lane":"SEARCH"}'
    assert captured["options"]["num_predict"] >= 768
    assert metrics["done_reason"] == "stop"


def test_router_reports_output_truncation_instead_of_model_unavailable(monkeypatch) -> None:
    import threading

    from src.app.services.local_model_roles import _reset_local_model_scheduler_for_tests
    from src.app.services.recommendation_core.router_model_call import execute_router_model

    monkeypatch.setenv("ROUTER_MODEL_ENABLED", "1")
    _reset_local_model_scheduler_for_tests()
    rendered, metrics = execute_router_model(
        "route this", 2.0, model="qwen3:14b",
        http_post=lambda *_args, **_kwargs: _TruncatedOllamaResponse(),
        injected_transport=True, gate=threading.BoundedSemaphore(1),
        runtime_contract={"queue_timeout_s": 0.2},
    )

    assert rendered == ""
    assert metrics["outcome"] == "truncated"
    assert metrics["failure_code"] == "router_output_truncated"
    assert metrics["done_reason"] == "length"
