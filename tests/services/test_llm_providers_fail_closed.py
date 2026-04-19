from __future__ import annotations

import pytest

from src.app.services.llm_providers import AnthropicProvider, OpenAIProvider, MistralProvider, get_provider


def test_get_provider_raises_when_no_keys_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    # OllamaProvider has no API key but requires OLLAMA_URL — clear it too
    monkeypatch.setenv("OLLAMA_URL", "")
    with pytest.raises(RuntimeError, match="No LLM provider API key is configured"):
        get_provider()


def test_openai_provider_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY not configured"):
        OpenAIProvider().generate("hello")


def test_anthropic_provider_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not configured"):
        AnthropicProvider().generate("hello")


def test_mistral_provider_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY not configured"):
        MistralProvider().generate("hello")
