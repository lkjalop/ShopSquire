import pytest

from src.app.services.local_model_roles import execute_local_model_role


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
