from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


class LLMGuardrails:
    """Basic output guardrails for demo purposes.

    Validates output format and checks for content violations like PII and
    prompt leakage markers. In production, integrate with a more complete
    policy engine.
    """

    def __init__(self):
        pass

    async def validate_output(self, output: str, expected_format: str, context: Dict[str, Any]) -> Tuple[bool, str, Any]:
        # 1) Format validation
        parsed: Any = output
        if expected_format == "json":
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                return False, "invalid_json", None
        elif expected_format == "sku_list":
            # Accept comma/space separated tokens
            tokens = [t.strip() for t in re.split(r"[,\s]+", output or "") if t.strip()]
            parsed = tokens
            if not tokens:
                return False, "empty_sku_list", None
        elif expected_format == "text":
            parsed = output or ""

        # 2) Content violations
        violations = []
        if self._contains_pii(output):
            violations.append("pii_in_output")
        if self._contains_prompt_leak(output):
            violations.append("prompt_leakage")
        if self._contains_harmful(output):
            violations.append("harmful_content")
        if violations:
            return False, violations[0], None

        return True, "valid", parsed

    def _contains_pii(self, text: str) -> bool:
        if not text:
            return False
        patterns = [
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # Email
            r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b\d{13,16}\b",  # Credit card-ish
        ]
        return any(re.search(p, text) for p in patterns)

    def _contains_prompt_leak(self, text: str) -> bool:
        if not text:
            return False
        leak = [
            r"(?i)my\s+instructions\s+are",
            r"(?i)system\s+prompt",
            r"(?i)i\s+am\s+programmed\s+to",
        ]
        return any(re.search(p, text) for p in leak)

    def _contains_harmful(self, text: str) -> bool:
        if not text:
            return False
        harmful = [
            r"(?i)how\s+to\s+make\s+a\s+bomb",
            r"(?i)kill\s+",
            r"(?i)steal\s+credit\s+cards",
        ]
        return any(re.search(p, text) for p in harmful)
