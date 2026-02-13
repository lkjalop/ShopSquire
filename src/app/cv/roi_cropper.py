from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List


class ROICropper:
    def crop(self, image_bytes: bytes, rois: List[Dict[str, Any]]) -> List[bytes]:
        return [c["image_bytes"] for c in self.crop_with_meta(image_bytes, rois)]

    def crop_with_meta(self, image_bytes: bytes, rois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rois:
            return [{"roi": {"label": "full_image", "confidence": 1.0, "xyxy": None}, "image_bytes": image_bytes}]
        try:
            from PIL import Image  # type: ignore
        except Exception:
            # No PIL: can't crop; just return the original bytes once.
            return [{"roi": rois[0], "image_bytes": image_bytes}]

        try:
            img = Image.open(BytesIO(image_bytes)).convert("RGB")
        except Exception:
            return [{"roi": rois[0], "image_bytes": image_bytes}]

        out: List[Dict[str, Any]] = []
        w, h = img.size
        for roi in rois or []:
            xyxy = roi.get("xyxy")
            if not (isinstance(xyxy, (list, tuple)) and len(xyxy) == 4):
                out.append({"roi": roi, "image_bytes": image_bytes})
                continue
            try:
                x1, y1, x2, y2 = [float(v) for v in xyxy]
                x1 = max(0, min(w, int(x1)))
                y1 = max(0, min(h, int(y1)))
                x2 = max(0, min(w, int(x2)))
                y2 = max(0, min(h, int(y2)))
                if x2 <= x1 or y2 <= y1:
                    raise ValueError("invalid_box")
                crop = img.crop((x1, y1, x2, y2))
                buf = BytesIO()
                crop.save(buf, format="PNG")
                out.append({"roi": roi, "image_bytes": buf.getvalue()})
            except Exception:
                out.append({"roi": roi, "image_bytes": image_bytes})
        return out
