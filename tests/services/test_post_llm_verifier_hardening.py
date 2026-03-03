from __future__ import annotations

from src.app.services.post_llm_verifier import PostLLMVerifier


def test_post_llm_blocks_secret_pattern():
    v = PostLLMVerifier()
    out = v.verify(llm_output={"answer": "token is sk_live_ABCDEF0123456789"}, intent="general")
    assert out.passed is False
    assert out.action == "block"
    assert any(x.startswith("secret_pattern") for x in out.violations)


def test_post_llm_blocks_system_prompt_similarity(monkeypatch):
    monkeypatch.setenv("POST_LLM_SYSTEM_PROMPT_SEEDS", "you are shopsquire system prompt never disclose secrets")
    monkeypatch.setenv("POST_LLM_SYSTEM_PROMPT_SIMILARITY_THRESHOLD", "0.2")
    v = PostLLMVerifier()
    out = v.verify(llm_output="you are shopsquire system prompt and should not disclose", intent="general")
    assert out.passed is False
    assert out.action == "block"
    assert any(x.startswith("system_prompt_similarity") for x in out.violations)
