from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import re

log = logging.getLogger(__name__)


class BasicCVTriage:
    """
    CV triage with two-tier analysis:
      1. Vision LLM (GPT-4o / Gemini / LLaVA) when image_bytes supplied and provider configured.
      2. Keyword/label fallback — always available, no external dependencies.
    """

    DAMAGE_KEYWORDS = {
        "physical": ["crack", "cracked", "broken", "dent", "scratch", "shattered", "hinge"],
        "cosmetic": ["scuff", "mark", "stain", "discolor"],
        "functional": ["error", "screen", "display", "black", "dead", "boot", "keyboard", "bsod", "blue screen", "stop code", "crash"],
        "packaging": ["box", "package", "torn", "crushed", "wet"],
    }

    COMPONENT_KEYWORDS = {
        "display": ["screen", "monitor", "lcd", "panel", "display"],
        "chassis": ["case", "body", "frame", "hinge", "chassis"],
        "keyboard": ["keyboard", "keys", "trackpad", "touchpad"],
        "power": ["charger", "battery", "adapter", "cable", "port"],
    }

    async def analyze(
        self,
        labels: list[str],
        extracted_text: str,
        *,
        image_bytes: bytes | None = None,
        mime: str = "image/jpeg",
        cv_pipeline_result: Dict[str, Any] | None = None,
    ) -> dict:
        # ── Tier 1: Vision LLM (when image_bytes available and provider configured) ──
        if image_bytes:
            try:
                from src.app.services.vision_reasoning import VisionReasoningService
                svc = VisionReasoningService()
                if svc.available:
                    vision = await svc.analyze_damage(image_bytes, mime)
                    if vision.error is None:
                        # Map VisionResult → triage dict shape expected by callers
                        sev_map = {
                            "critical": "critical",
                            "major": "major",
                            "minor": "minor",
                            "none": "undetermined",
                        }
                        return {
                            "status": "analyzed",
                            "damage_type": vision.damage_type or "unknown",
                            "component": vision.damaged_component,
                            "severity": sev_map.get(vision.damage_severity or "", "undetermined"),
                            "confidence": vision.visual_confidence,
                            "serial_number": None,
                            "extracted_text": (extracted_text or "")[:500],
                            "raw_labels": (labels or [])[:10],
                            "needs_human_review": vision.visual_confidence < 0.6,
                            "ai_disclaimer": "vision_llm",
                            "plain_english": vision.plain_english_summary,
                            "provider": vision.provider_used,
                        }
                    log.debug("VisionReasoningService failed, falling back to keyword: %s", vision.error)
            except Exception as exc:
                log.debug("cv_triage vision LLM attempt failed: %s", exc)

        # ── Tier 2: Keyword / label fallback ──────────────────────────────────────
        # Attempt to supplement empty labels/text from cv_pipeline output
        effective_labels = list(labels or [])
        effective_text = extracted_text or ""
        insufficient_data = False

        if cv_pipeline_result and isinstance(cv_pipeline_result, dict):
            # Pull OCR text from the pipeline when caller text is empty
            if not effective_text:
                for img in cv_pipeline_result.get("images") or []:
                    ocr = img.get("ocr") or {}
                    t = ocr.get("best_text") or ""
                    if t:
                        effective_text = f"{effective_text} {t}".strip()
            # Pull ROI class names as pseudo-labels
            if not effective_labels:
                for img in cv_pipeline_result.get("images") or []:
                    for roi in img.get("rois") or []:
                        cls = roi.get("class") or roi.get("label") or ""
                        if cls and cls not in effective_labels:
                            effective_labels.append(str(cls))

        damage_type = self._classify_damage(effective_labels)
        component = self._identify_component(effective_labels)
        serial_number = self._extract_serial(effective_text)
        confidence = self._calculate_confidence(effective_labels, damage_type)

        # Detect "insufficient data" case: no labels, no text, nothing to analyze
        if not effective_labels and not effective_text.strip():
            insufficient_data = True

        severity = self._estimate_severity(effective_labels, confidence, insufficient_data=insufficient_data)
        severity_reason = None
        if insufficient_data:
            severity_reason = "no_labels_or_text_extracted"

        result: Dict[str, Any] = {
            "status": "analyzed",
            "damage_type": damage_type,
            "component": component,
            "severity": severity,
            "confidence": confidence,
            "serial_number": serial_number,
            "extracted_text": (effective_text or "")[:500],
            "raw_labels": effective_labels[:10],
            "needs_human_review": confidence < 0.6 or insufficient_data,
            "ai_disclaimer": "preliminary",
        }
        if severity_reason:
            result["severity_reason"] = severity_reason
        if insufficient_data:
            result["insufficient_data"] = True
        return result

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

    def _estimate_severity(
        self,
        labels: list[str],
        confidence: float,
        *,
        insufficient_data: bool = False,
    ) -> str:
        if insufficient_data:
            return "insufficient_data"
        severe = ["shattered", "destroyed", "broken", "dead"]
        if any(ind in " ".join(labels).lower() for ind in severe):
            return "critical"
        elif confidence > 0.7:
            return "major"
        elif confidence > 0.5:
            return "minor"
        return "undetermined"
