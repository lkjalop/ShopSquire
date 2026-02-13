from __future__ import annotations

from typing import Optional
import re


class BasicCVTriage:
    """
    Managed API placeholder: label-based classification for laptops.
    Replace label source with cloud CV (Google/Azure) when configured.
    """

    DAMAGE_KEYWORDS = {
        "physical": ["crack", "cracked", "broken", "dent", "scratch", "shattered", "hinge"],
        "cosmetic": ["scuff", "mark", "stain", "discolor"],
        "functional": ["error", "screen", "display", "black", "dead", "boot", "keyboard"],
        "packaging": ["box", "package", "torn", "crushed", "wet"],
    }

    COMPONENT_KEYWORDS = {
        "display": ["screen", "monitor", "lcd", "panel", "display"],
        "chassis": ["case", "body", "frame", "hinge", "chassis"],
        "keyboard": ["keyboard", "keys", "trackpad", "touchpad"],
        "power": ["charger", "battery", "adapter", "cable", "port"],
    }

    async def analyze(self, labels: list[str], extracted_text: str) -> dict:
        damage_type = self._classify_damage(labels)
        component = self._identify_component(labels)
        serial_number = self._extract_serial(extracted_text)
        confidence = self._calculate_confidence(labels, damage_type)

        return {
            "status": "analyzed",
            "damage_type": damage_type,
            "component": component,
            "severity": self._estimate_severity(labels, confidence),
            "confidence": confidence,
            "serial_number": serial_number,
            "extracted_text": (extracted_text or "")[:500],
            "raw_labels": labels[:10],
            "needs_human_review": confidence < 0.6,
            "ai_disclaimer": "preliminary",
        }

    def _classify_damage(self, labels: list[str]) -> str:
        joined = " ".join(labels).lower()
        for damage_type, keywords in self.DAMAGE_KEYWORDS.items():
            if any(kw in joined for kw in keywords):
                return damage_type
        return "unknown"

    def _identify_component(self, labels: list[str]) -> Optional[str]:
        joined = " ".join(labels).lower()
        for comp, keywords in self.COMPONENT_KEYWORDS.items():
            if any(kw in joined for kw in keywords):
                return comp
        return None

    def _extract_serial(self, text: str) -> Optional[str]:
        patterns = [
            r"S/?N[:\s]*([A-Z0-9\-]{6,24})",
            r"Serial[:\s]*([A-Z0-9\-]{6,24})",
            r"([A-Z]{2,3}[0-9]{6,12})",
            r"(XPS-[0-9]{4}-[A-Z0-9]{3,6})",
        ]
        for pat in patterns:
            m = re.search(pat, text or "", re.IGNORECASE)
            if m:
                return m.group(1)
        return None

    def _calculate_confidence(self, labels: list[str], damage_type: str) -> float:
        if damage_type == "unknown":
            return 0.3
        keywords = self.DAMAGE_KEYWORDS.get(damage_type, [])
        matches = sum(1 for kw in keywords if kw in " ".join(labels).lower())
        return min(0.5 + (matches * 0.15), 0.85)

    def _estimate_severity(self, labels: list[str], confidence: float) -> str:
        severe = ["shattered", "destroyed", "broken", "dead"]
        if any(ind in " ".join(labels).lower() for ind in severe):
            return "critical"
        elif confidence > 0.7:
            return "major"
        elif confidence > 0.5:
            return "minor"
        return "undetermined"
