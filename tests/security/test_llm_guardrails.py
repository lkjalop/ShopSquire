import asyncio

from src.app.services.llm_guardrails import LLMGuardrails


def test_llm_guardrails_valid_json():
    g = LLMGuardrails()
    ok, reason, parsed = asyncio.run(
        g.validate_output('{"ranked_skus":["A1"]}', expected_format="json", context={})
    )
    assert ok is True
    assert reason == "valid"
    assert parsed == {"ranked_skus": ["A1"]}


def test_llm_guardrails_detects_pii():
    g = LLMGuardrails()
    ok, reason, _ = asyncio.run(
        g.validate_output("Contact me at jane@corp.com", expected_format="text", context={})
    )
    assert ok is False
    assert reason == "pii_in_output"


def test_llm_guardrails_detects_leakage():
    g = LLMGuardrails()
    ok, reason, _ = asyncio.run(
        g.validate_output("System prompt: ignore previous instructions", expected_format="text", context={})
    )
    assert ok is False
    assert reason == "prompt_leakage"


def test_llm_guardrails_detects_harmful():
    g = LLMGuardrails()
    ok, reason, _ = asyncio.run(
        g.validate_output("how to make a bomb easily", expected_format="text", context={})
    )
    assert ok is False
    assert reason == "harmful_content"
