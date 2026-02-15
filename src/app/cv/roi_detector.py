from __future__ import annotations

from typing import Any, Dict, List, Optional


class ROIDetector:
    """ROI detector wrapper.

    - When Ultralytics/YOLO is available and a model path is configured, returns YOLO detections.
    - Otherwise falls back to a single "full_image" ROI so downstream stages still run.
    """

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path
        self._detector = None

    def detect(self, image_bytes: bytes, *, allowlist: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        allow = set([a for a in (allowlist or []) if a])
        # Try to reuse the Tier2 detector implementation when available.
        try:
            from src.app.services.cv_object_detector import CVObjectDetector

            if self._detector is None and self.model_path:
                self._detector = CVObjectDetector(model_path=self.model_path)
            detector = self._detector
            if detector is None:
                raise RuntimeError("no_detector")
            dets = detector.detect(image_bytes) or []
            out: List[Dict[str, Any]] = []
            for d in dets:
                label = d.get("label")
                if allow and label and label not in allow:
                    continue
                out.append(
                    {
                        "label": label or "roi",
                        "confidence": float(d.get("confidence") or 0.0),
                        "xyxy": d.get("xyxy"),
                        "source": "yolo",
                    }
                )
            if out:
                return out
        except Exception:
            import logging

            logging.getLogger("shopsquire.cv.roi_detector").exception("ROI detector failed, falling back to full_image")

        # Fallback ROI: run the rest of the pipeline on the full image.
        return [{"label": "full_image", "confidence": 1.0, "xyxy": None, "source": "fallback"}]
