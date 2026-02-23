from __future__ import annotations

import re
from typing import Any, Dict

from src.app.services.intake_gate import enforce_qr_url_allowlist, sanitize_ocr_text

from src.app.security.observer import analyze_payload


class SecurityAwareLLM:
    """LLM wrapper with security awareness."""

    def __init__(self, base_llm):
        self.llm = base_llm

    async def generate(self, prompt: str, context: Dict | None = None) -> Dict:
        context = dict(context or {})
        sanitized_context = self._sanitize_context(context)
        safe_prompt, prompt_meta = sanitize_ocr_text(str(prompt or ""), max_len=40_000)
        if bool(prompt_meta.get("removed_instruction_hits")):
            sanitized_context.setdefault("sanitization", {})
            sanitized_context["sanitization"]["prompt_instruction_hits"] = int(prompt_meta.get("removed_instruction_hits") or 0)
        pre_check = analyze_payload({"prompt": safe_prompt, **sanitized_context})
        if pre_check.get("severity") in ("high", "critical"):
            return {
                "response": None,
                "blocked": True,
                "reason": pre_check.get("severity"),
                "security": pre_check.get("details"),
            }
        qr_policy = self._qr_policy_from_context(sanitized_context)
        if int(qr_policy.get("blocked_count") or 0) > 0:
            return {
                "response": None,
                "blocked": True,
                "reason": "qr_url_not_allowlisted",
                "security": {"qr_policy": qr_policy},
            }
        response = await self.llm.generate(safe_prompt)
        post_check = analyze_payload({"response": response, **sanitized_context})
        if post_check.get("severity") in ("high", "critical"):
            return {
                "response": None,
                "blocked": True,
                "reason": "unsafe_output",
                "security": post_check.get("details"),
            }
        return {
            "response": response,
            "blocked": False,
            "security": {
                **dict(post_check.get("details") or {}),
                "qr_policy": qr_policy,
                "sanitization": sanitized_context.get("sanitization") or {},
            },
        }

    def _sanitize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(context or {})
        san_meta: Dict[str, Any] = {}
        for key in ("ocr_text", "extracted_text", "attachment_text", "image_text"):
            val = out.get(key)
            if not isinstance(val, str) or not val.strip():
                continue
            cleaned, meta = sanitize_ocr_text(val, max_len=40_000)
            out[key] = cleaned
            if bool(meta.get("changed")):
                san_meta[key] = meta
        if san_meta:
            out["sanitization"] = san_meta
        return out

    def _qr_policy_from_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        urls = []
        raw = context.get("qr_urls")
        if isinstance(raw, list):
            urls.extend([str(x) for x in raw if str(x or "").strip()])
        for key in ("ocr_text", "extracted_text", "attachment_text", "image_text"):
            text = context.get(key)
            if isinstance(text, str) and text:
                urls.extend([m.group(0) for m in re.finditer(r"https?://[^\s<>()\"']+", text)])
        return enforce_qr_url_allowlist(urls)
