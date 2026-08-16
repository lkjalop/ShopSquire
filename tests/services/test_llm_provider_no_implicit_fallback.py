import asyncio

import pytest

from src.app.services import llm_provider


def test_missing_local_deployment_never_invokes_cloud_fallback(monkeypatch):
    monkeypatch.setattr(llm_provider, "OLLAMA_URL", "")

    with pytest.raises(RuntimeError, match="OLLAMA_URL_missing"):
        asyncio.run(llm_provider.ollama_generate("qwen3:14b", "hello"))

    assert not hasattr(llm_provider, "_openai_generate_fallback")
