from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

from src.app.services.ollama_client import OllamaClient
from src.app.services.llm_guardrails import LLMGuardrails


router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.get("/llm_guardrails")
async def llm_guardrails_demo(prompt: str, expected_format: Optional[str] = "text") -> Dict:
    """Run a simple Ollama generation and validate with guardrails.

    Returns blocked/allowed with reason to demonstrate safe-agent behavior.
    """
    client = OllamaClient()
    rails = LLMGuardrails()

    # Try local Ollama; fall back to echoing the prompt if unavailable.
    text = prompt
    try:
        if await client.health():
            res = await client.generate(prompt=prompt)
            text = res.text or text
        else:
            text = prompt
    except Exception:
        text = prompt

    ok, reason, parsed = await rails.validate_output(text, expected_format or "text", context={})
    if not ok:
        # Blocked output demo
        return {
            "status": "blocked",
            "reason": reason,
            "expected_format": expected_format,
            "raw": text,
        }

    return {
        "status": "allowed",
        "expected_format": expected_format,
        "parsed": parsed,
    }
