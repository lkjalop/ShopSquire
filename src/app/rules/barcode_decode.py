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
        def _decode_once(detector: Any, frame: Any) -> List[Dict[str, Any]]:
            out_local: List[Dict[str, Any]] = []
            try:
                ok, decoded_info, _points, _ = detector.detectAndDecodeMulti(frame)  # type: ignore
                if ok and decoded_info:
                    for s in decoded_info:
                        if s:
                            out_local.append({"type": "QR_CODE", "data": str(s)})
            except Exception:
                pass
            if out_local:
                return out_local
            try:
                data, _pts, _ = detector.detectAndDecode(frame)
                if data:
                    out_local.append({"type": "QR_CODE", "data": str(data)})
            except Exception:
                pass
            return out_local

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return []
        detector = cv2.QRCodeDetector()
        h, w = img.shape[:2]
        variants: List[Any] = [img]
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            variants.append(gray)
            variants.append(cv2.GaussianBlur(gray, (3, 3), 0))
            variants.append(cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 5))
            if min(h, w) <= 1800:
                for scale in (1.5, 2.0, 3.0):
                    variants.append(cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))
            # Many adversarial overlays place QR in corners; scan corner crops too.
            ch = max(64, int(h * 0.45))
            cw = max(64, int(w * 0.45))
            corners = [
                gray[0:ch, 0:cw],
                gray[0:ch, max(0, w - cw):w],
                gray[max(0, h - ch):h, 0:cw],
                gray[max(0, h - ch):h, max(0, w - cw):w],
            ]
            for c in corners:
                if c is None or c.size == 0:
                    continue
                variants.append(c)
                variants.append(cv2.resize(c, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC))
        except Exception:
            pass

        seen_data = set()
        out: List[Dict[str, Any]] = []
        for frame in variants:
            decoded = _decode_once(detector, frame)
            if not decoded:
                continue
            for item in decoded:
                d = str(item.get("data") or "").strip()
                if not d or d in seen_data:
                    continue
                seen_data.add(d)
                out.append({"type": "QR_CODE", "data": d})
            if out:
                return out
        return out
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
