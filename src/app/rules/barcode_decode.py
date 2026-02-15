from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import logging


@dataclass
class BarcodeDecodeResult:
    ok: bool
    codes: List[Dict[str, Any]]
    reasons: List[str]


def _try_decode_pyzbar(image_bytes: bytes) -> List[Dict[str, Any]]:
    try:
        from PIL import Image  # type: ignore
        from io import BytesIO
        from pyzbar.pyzbar import decode  # type: ignore
    except Exception as e:
        logging.getLogger(__name__).debug("pyzbar import failed: %s", e)
        return []
    try:
        img = Image.open(BytesIO(image_bytes))
        decoded = decode(img)
        out: List[Dict[str, Any]] = []
        for d in decoded:
            try:
                out.append(
                    {
                        "type": getattr(d, "type", None),
                        "data": (getattr(d, "data", b"") or b"").decode("utf-8", errors="ignore"),
                    }
                )
            except Exception:
                logging.getLogger(__name__).exception("pyzbar: failed to decode one symbol")
        return out
    except Exception:
        logging.getLogger(__name__).exception("pyzbar: failed to decode image")
        return []


def _try_decode_opencv(image_bytes: bytes) -> List[Dict[str, Any]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception as e:
        logging.getLogger(__name__).debug("opencv import failed: %s", e)
        return []
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []
        detector = cv2.QRCodeDetector()
        out: List[Dict[str, Any]] = []
        # prefer multi if available
        try:
            ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)  # type: ignore
            if ok and decoded_info:
                for s in decoded_info:
                    if s:
                        out.append({"type": "QR_CODE", "data": str(s)})
                return out
        except Exception:
            # fall back to single
            try:
                data, pts, _ = detector.detectAndDecode(img)
                if data:
                    out.append({"type": "QR_CODE", "data": str(data)})
                    return out
            except Exception:
                logging.getLogger(__name__).exception("opencv: detectAndDecode failed")
                return []
        return []
    except Exception:
        logging.getLogger(__name__).exception("opencv: failed to decode image")
        return []


def decode_barcodes(images: List[Tuple[str, bytes]]) -> BarcodeDecodeResult:
    codes: List[Dict[str, Any]] = []
    reasons_set = set()
    for fname, b in images or []:
        # Try pyzbar first
        pyz = _try_decode_pyzbar(b)
        if pyz:
            for c in pyz:
                c["filename"] = fname
                codes.append(c)
            reasons_set.add("pyzbar_decoded")
            continue
        else:
            reasons_set.add("pyzbar_no_result")

        # Try OpenCV fallback
        op = _try_decode_opencv(b)
        if op:
            for c in op:
                c["filename"] = fname
                codes.append(c)
            reasons_set.add("opencv_decoded")
        else:
            reasons_set.add("opencv_no_result")

    ok = bool(codes)
    reasons: List[str] = []
    # Collate reasons into ordered list
    for r in sorted(reasons_set):
        reasons.append(r)
    if not ok and not reasons:
        reasons.append("no_codes")
    if not ok:
        # keep a generic no_codes reason if no decoder succeeded
        if "no_codes" not in reasons:
            reasons.append("no_codes")
    return BarcodeDecodeResult(ok=ok, codes=codes, reasons=reasons)

