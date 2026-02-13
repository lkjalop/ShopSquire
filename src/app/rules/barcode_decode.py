from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


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
    except Exception:
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
                pass
        return out
    except Exception:
        return []


def decode_barcodes(images: List[Tuple[str, bytes]]) -> BarcodeDecodeResult:
    codes: List[Dict[str, Any]] = []
    for fname, b in images or []:
        for c in _try_decode_pyzbar(b):
            c["filename"] = fname
            codes.append(c)
    ok = bool(codes)
    reasons = []
    if not ok:
        reasons.append("no_codes")
    return BarcodeDecodeResult(ok=ok, codes=codes, reasons=reasons)

