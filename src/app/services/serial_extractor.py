from __future__ import annotations

import re
from io import BytesIO
from typing import Dict, List, Optional


class SerialExtractor:
    """Enhanced serial number extraction from images."""

    SERIAL_PATTERNS = {
        "dell": r"[A-Z0-9]{7}",
        "hp": r"[A-Z0-9]{10}",
        "lenovo": r"[A-Z0-9]{8,10}",
        "apple": r"[A-Z0-9]{12}",
        "generic": r"[A-Z0-9]{6,15}",
    }

    def extract_serial(self, image_bytes: bytes, manufacturer: str | None = None) -> Dict[str, Optional[str] | List[str] | float]:
        try:
            from PIL import Image
            import pytesseract  # type: ignore
        except Exception:
            return {
                "serial": None,
                "confidence": 0.0,
                "alternatives": [],
                "raw_ocr": "",
                "error": "missing_deps",
            }
        try:
            img = Image.open(BytesIO(image_bytes))
        except Exception:
            return {"serial": None, "confidence": 0.0, "alternatives": [], "raw_ocr": "", "error": "invalid_image"}

        img = self._preprocess_for_ocr(img)
        results = []
        for cfg in ("--psm 6", "--psm 7", "--psm 11"):
            try:
                results.append(pytesseract.image_to_string(img, config=cfg))
            except Exception:
                continue
        all_text = " ".join(results)
        candidates = self._extract_candidates(all_text, manufacturer)
        bounding_boxes = self._extract_boxes(img, pytesseract)
        return {
            "serial": candidates[0] if candidates else None,
            "confidence": self._calculate_confidence(candidates, bounding_boxes),
            "alternatives": candidates[1:5] if len(candidates) > 1 else [],
            "raw_ocr": all_text[:500],
            "bounding_boxes": bounding_boxes,
        }

    def _extract_candidates(self, text: str, manufacturer: str | None) -> List[str]:
        pattern = self.SERIAL_PATTERNS.get((manufacturer or "").lower(), self.SERIAL_PATTERNS["generic"])
        return list(dict.fromkeys(re.findall(pattern, text.upper())))

    def _calculate_confidence(self, candidates: List[str], boxes: List[dict]) -> float:
        if not candidates:
            return 0.0
        if boxes:
            confs = [b.get("conf", 0.0) for b in boxes if isinstance(b.get("conf"), (int, float))]
            if confs:
                return max(0.0, min(1.0, (sum(confs) / len(confs)) / 100.0))
        if len(candidates) == 1:
            return 0.7
        return 0.5

    def _extract_boxes(self, img, pytesseract) -> List[dict]:
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        except Exception:
            return []
        boxes = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data.get("text", [""])[i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data.get("conf", [0])[i])
            except Exception:
                conf = 0.0
            boxes.append(
                {
                    "text": text,
                    "conf": conf,
                    "left": int(data.get("left", [0])[i]),
                    "top": int(data.get("top", [0])[i]),
                    "width": int(data.get("width", [0])[i]),
                    "height": int(data.get("height", [0])[i]),
                }
            )
        return boxes

    def _preprocess_for_ocr(self, img):
        try:
            import cv2  # type: ignore
            import numpy as np
        except Exception:
            return img
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray)
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return img.__class__.fromarray(binary)
