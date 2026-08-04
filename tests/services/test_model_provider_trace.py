from __future__ import annotations

from src.app.services import llm_providers


class _Response:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "grounded answer"}}]}


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
