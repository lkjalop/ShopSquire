from __future__ import annotations

from typing import Dict

from src.app.security.observer import analyze_payload


class SecurityAwareLLM:
    """LLM wrapper with security awareness."""

    def __init__(self, base_llm):
        self.llm = base_llm

    async def generate(self, prompt: str, context: Dict | None = None) -> Dict:
        context = context or {}
        pre_check = analyze_payload({"prompt": prompt, **context})
        if pre_check.get("severity") in ("high", "critical"):
            return {
                "response": None,
                "blocked": True,
                "reason": pre_check.get("severity"),
                "security": pre_check.get("details"),
            }
        response = await self.llm.generate(prompt)
        post_check = analyze_payload({"response": response, **context})
        if post_check.get("severity") in ("high", "critical"):
            return {
                "response": None,
                "blocked": True,
                "reason": "unsafe_output",
                "security": post_check.get("details"),
            }
        return {"response": response, "blocked": False, "security": post_check.get("details")}
