from __future__ import annotations

import re
import unicodedata
from typing import Dict, List


class DeceptionDetector:
    """Detect deceptive or manipulative language patterns."""

    URGENCY_PATTERNS = [
        r"must\s+(process|approve|complete)\s+(now|immediately|today)",
        r"urgent|emergency|critical\s+situation",
        r"time\s+sensitive|deadline",
        r"will\s+expire|limited\s+time",
    ]
    AUTHORITY_PATTERNS = [
        r"i\s+am\s+(from|with)\s+(corporate|headquarters|management)",
        r"(ceo|cfo|director|manager)\s+authorized",
        r"executive\s+override",
        r"special\s+permission",
    ]
    SOCIAL_ENGINEERING_PATTERNS = [
        r"my\s+(boss|manager|supervisor)\s+said",
        r"(they|she|he)\s+told\s+me\s+to",
        r"internal\s+request",
        r"off\s+the\s+record",
    ]

    def analyze(self, text: str) -> Dict:
        signals = []
        text_lower = (text or "").lower()
        for pattern in self.URGENCY_PATTERNS:
            if re.search(pattern, text_lower):
                signals.append({"type": "urgency_manipulation", "pattern": pattern, "severity": "medium"})
        for pattern in self.AUTHORITY_PATTERNS:
            if re.search(pattern, text_lower):
                signals.append({"type": "authority_impersonation", "pattern": pattern, "severity": "high"})
        for pattern in self.SOCIAL_ENGINEERING_PATTERNS:
            if re.search(pattern, text_lower):
                signals.append({"type": "social_engineering", "pattern": pattern, "severity": "high"})
        signals.extend(self._analyze_unicode(text or ""))
        score = self._calculate_score(signals)
        return {
            "signals": signals,
            "deception_score": score,
            "recommendation": self._get_recommendation(signals),
        }

    def _analyze_unicode(self, text: str) -> List[Dict]:
        signals = []
        for char in text:
            if ord(char) > 127:
                name = unicodedata.name(char, "")
                if any(x in name.lower() for x in ["cyrillic", "greek", "armenian"]):
                    signals.append({"type": "homoglyph_attack", "char": char, "severity": "high"})
        for zw in ["\u200b", "\u200c", "\u200d", "\ufeff"]:
            if zw in text:
                signals.append({"type": "hidden_character", "severity": "medium"})
        return signals

    def _calculate_score(self, signals: List[Dict]) -> float:
        score = 0.0
        for s in signals:
            if s.get("severity") == "high":
                score += 0.4
            elif s.get("severity") == "medium":
                score += 0.2
        return min(1.0, score)

    def _get_recommendation(self, signals: List[Dict]) -> str:
        if any(s.get("severity") == "high" for s in signals):
            return "review"
        if signals:
            return "monitor"
        return "allow"
