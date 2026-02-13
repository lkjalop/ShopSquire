from __future__ import annotations

from typing import Any, Dict, List


COCO_ALIAS = {
    "laptop": "device",
    "tv": "screen",
    "cell phone": "device",
    "keyboard": "keyboard",
    "mouse": "mouse",
    "book": "document",
    "suitcase": "box",
    "handbag": "box",
    "backpack": "box",
    "person": "person",
}


class CVObjectDetector:
    def __init__(self, model_path: str | None = None):
        self.model_path = model_path
        self.model = None
        self._load()

    def _load(self) -> None:
        if not self.model_path:
            return
        try:
            import os
            if not os.path.exists(self.model_path):
                alt = os.path.join("models", os.path.basename(self.model_path))
                if os.path.exists(alt):
                    self.model_path = alt
        except Exception:
            pass
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception:
            return
        try:
            self.model = YOLO(self.model_path)
        except Exception:
            self.model = None

    def detect(self, image_bytes: bytes) -> List[Dict[str, Any]]:
        if not self.model:
            return []
        try:
            # Ultralytics models don't accept raw bytes directly; convert to a
            # numpy RGB array when possible.
            inp: Any = image_bytes
            try:
                from PIL import Image  # type: ignore
                import numpy as np  # type: ignore

                img = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
                inp = np.array(img)
            except Exception:
                inp = image_bytes

            results = self.model(inp)
            detections = []
            for r in results:
                names = r.names if hasattr(r, "names") else {}
                for box in r.boxes:
                    label = names.get(int(box.cls)) if isinstance(names, dict) else None
                    detections.append(
                        {
                            "label": label,
                            "confidence": float(box.conf),
                            "xyxy": [float(x) for x in box.xyxy[0].tolist()],
                        }
                    )
            return detections
        except Exception:
            return []

    @staticmethod
    def summarize(detections: List[Dict[str, Any]]) -> Dict[str, Any]:
        labels = [d.get("label") for d in detections if d.get("label")]
        mapped = [COCO_ALIAS.get(l, l) for l in labels]
        return {
            "labels": labels,
            "mapped": mapped,
            "unique": sorted(set(mapped)),
            "counts": {m: mapped.count(m) for m in set(mapped)},
        }
