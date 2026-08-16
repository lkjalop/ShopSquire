import threading
import time

import pytest

from src.app.services.model_execution_gateway import (
    AgentRunEventLedger,
    ModelDeployment,
    ModelExecutionGateway,
    ModelExecutionRequest,
    execute_model,
    sha256_text,
)


def _deployment(**changes):
    values = {
        "deployment_id": "local-qwen-narrator",
        "provider": "ollama",
        "endpoint": "http://127.0.0.1:11434/api/generate",
        "endpoint_identity": "127.0.0.1",
        "model_artifact_id": "qwen3:14b@sha256:test",
        "model_artifact_digest": "a" * 64,
        "jurisdiction": "local-development",
        "locality": "loopback",
        "allowed_roles": {"narrator", "query_planner"},
        "allowed_data_classes": {"public_catalog", "buyer_workload"},
        "allowed_capabilities": set(),
        "retention_policy": "no-provider-retention",
        "training_policy": "disabled",
        "policy_version": "portfolio-v1",
        "artifact_verification_status": "verified",
    }
    values.update(changes)
    return ModelDeployment.model_validate(values)


def _request(prompt="hello", **changes):
    values = {
        "tenant_id": "tenant-a", "purpose": "evidence_narration", "role": "narrator",
        "deployment_id": "local-qwen-narrator",
        "model_artifact_id": "qwen3:14b@sha256:test",
        "prompt_id": "shelf-narration", "prompt_version": "v1",
        "prompt_hash": sha256_text(prompt), "context_hash": sha256_text("context"),
        "data_classes": {"public_catalog"}, "timeout_ms": 100,
    }
    values.update(changes)
    return ModelExecutionRequest.model_validate(values)


def test_gateway_executes_one_enrolled_deployment_and_records_hashes_only():
    prompt = "buyer-safe prompt"
    ledger = AgentRunEventLedger()
    result = execute_model(
        _request(prompt), _deployment(), prompt=prompt,
        transport=lambda sent, _deployment, _request: f"answer:{sent}", ledger=ledger,
    )

    assert result.status == "completed" and result.text == f"answer:{prompt}"
    events = ledger.events_for(result.run_id, tenant_id="tenant-a")
    assert [event.event_type for event in events] == ["accepted", "completed"]
    assert all("prompt" not in event.details for event in events)
    assert events[-1].details["output_hash"] == result.output_hash


def test_gateway_rejects_artifact_or_prompt_identity_mismatch_before_transport():
    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return "no"

    result = execute_model(
        _request(model_artifact_id="wrong"), _deployment(), prompt="hello",
        transport=transport, ledger=AgentRunEventLedger(),
    )

    assert result.status == "blocked"
    assert result.failure_code == "model_artifact_identity_mismatch"
    assert called is False


def test_model_can_never_receive_commerce_capability():
    with pytest.raises(ValueError, match="model_deployment_cannot_have_commerce_capability"):
        _deployment(allowed_capabilities={"cart_mutation"})


def test_remote_endpoint_cannot_masquerade_as_loopback():
    with pytest.raises(ValueError, match="loopback_deployment_not_loopback"):
        _deployment(endpoint="https://api.example/model", endpoint_identity="api.example")


def test_slow_result_times_out_and_is_quarantined():
    released = threading.Event()
    ledger = AgentRunEventLedger()

    def slow(*_args):
        time.sleep(0.1)
        released.set()
        return "late"

    result = execute_model(
        _request(timeout_ms=50), _deployment(), prompt="hello", transport=slow,
        ledger=ledger,
    )

    assert result.status == "timeout"
    assert result.text is None and result.late_result_quarantined is True
    assert released.wait(0.3)
    events = ledger.events_for(result.run_id, tenant_id="tenant-a")
    assert events[-1].event_type == "late_result_quarantined"


def test_cancel_before_dispatch_never_calls_transport():
    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return "no"

    result = execute_model(
        _request(), _deployment(), prompt="hello", transport=transport,
        ledger=AgentRunEventLedger(), cancellation_requested=lambda: True,
    )

    assert result.status == "cancelled" and called is False


def test_gateway_rejects_unenrolled_deployment():
    gateway = ModelExecutionGateway([])

    with pytest.raises(ValueError, match="model_deployment_not_enrolled"):
        gateway.execute(
            _request(), prompt="hello", transport=lambda *_args: "not called",
        )


def test_gateway_defaults_to_ollama_only_and_blocks_unverified_artifacts():
    with pytest.raises(ValueError, match="model_provider_not_allowed:openai"):
        ModelExecutionGateway([_deployment(provider="openai")])

    result = execute_model(
        _request(), _deployment(artifact_verification_status="unverified"),
        prompt="hello", transport=lambda *_args: "not called",
        ledger=AgentRunEventLedger(),
    )
    assert result.status == "blocked"
    assert result.failure_code == "model_artifact_not_verified"


def test_agent_event_ledger_strips_raw_context_and_scrubs_nested_pii():
    ledger = AgentRunEventLedger()
    event = ledger.append(
        _request(), _deployment(), "blocked",
        prompt="secret", nested={"buyer_address": "hidden", "email": "buyer@example.com"},
    )

    assert "prompt" not in event.details
    assert "buyer_address" not in event.details["nested"]
    assert "buyer@example.com" not in str(event.details)


def test_ledger_failure_blocks_dispatch_and_releases_gateway_capacity():
    class BrokenLedger:
        def append(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    called = False

    def transport(*_args):
        nonlocal called
        called = True
        return "must not run"

    result = execute_model(
        _request(), _deployment(), prompt="hello", transport=transport,
        ledger=BrokenLedger(),
    )
    assert result.status == "blocked"
    assert result.failure_code == "agent_ledger_persistence_failed"
    assert called is False

    # The failed audit write must not leak an execution semaphore slot.
    follow_up = execute_model(
        _request(), _deployment(), prompt="hello", transport=lambda *_args: "ok",
        ledger=AgentRunEventLedger(),
    )
    assert follow_up.status == "completed"
