from __future__ import annotations

import random
import re
from typing import Dict


class EthicalAIGuard:
    """Ensure AI responses are ethical and empathetic."""

    EMPATHY_TRIGGERS = [
        "frustrated",
        "angry",
        "upset",
        "disappointed",
        "confused",
        "lost",
        "help",
        "please",
    ]

    def enhance_response(self, response: str, context: Dict) -> str:
        sentiment = context.get("sentiment", "neutral")
        if sentiment == "negative":
            response = self._add_empathy_prefix(response)
        if self._could_cause_harm(response):
            response = self._add_safety_disclaimer(response)
        if self._has_potential_bias(response):
            response = self._neutralize_bias(response)
        return response

    def _add_empathy_prefix(self, response: str) -> str:
        prefixes = [
            "I understand this can be frustrating. ",
            "I'm sorry you're experiencing this. ",
            "I want to help resolve this for you. ",
        ]
        return random.choice(prefixes) + response

    def _could_cause_harm(self, response: str) -> bool:
        return bool(re.search(r"\\bunsafe\\b|\\brisky\\b", response.lower()))

    def _add_safety_disclaimer(self, response: str) -> str:
        return response + " For safety, please verify details with support."

    def _has_potential_bias(self, response: str) -> bool:
        return False

    def _neutralize_bias(self, response: str) -> str:
        return response
