from __future__ import annotations

import re
from typing import Any, Dict, List


_AMOUNT_RE = re.compile(r"\b(?:usd|aud|\$)\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(20[0-9]{2}[/-][01]?[0-9][/-][0-3]?[0-9]|[0-3]?[0-9][/-][01]?[0-9][/-]20[0-9]{2})\b")
_INV_NO_RE = re.compile(r"\b(?:invoice(?:\s*no|\s*#| number)?)[\s:]*([A-Z0-9-]{4,})", re.IGNORECASE)
_PO_NO_RE = re.compile(r"\b(?:po(?:\s*no|\s*#| number)?|purchase order)[\s:]*([A-Z0-9-]{4,})", re.IGNORECASE)
_BOL_NO_RE = re.compile(r"\b(?:bol|b\/l|bill of lading(?:\s*no|\s*#| number)?)[\s:]*([A-Z0-9-]{4,})", re.IGNORECASE)
_CARRIER_RE = re.compile(r"\b(carrier|consignee|shipper|scac)[\s:]*([A-Za-z0-9 .&,'-]{2,80})", re.IGNORECASE)
_TRACKING_RE = re.compile(r"\b(?:tracking(?:\s*no|\s*#| number)?|awb|consignment)[\s:]*([A-Z0-9-]{6,})", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _pick_first(pat: re.Pattern[str], text: str) -> str | None:
    m = pat.search(text)
    if not m:
        return None
    try:
        return str(m.group(1)).strip()
    except Exception:
        return None


def _pick_all(pat: re.Pattern[str], text: str, limit: int = 5) -> List[str]:
    out: List[str] = []
    for m in pat.finditer(text):
        try:
            out.append(str(m.group(1)).strip())
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def _extract_with_provenance(
    text: str,
    *,
    field: str,
    pat: re.Pattern[str],
    confidence: float,
) -> tuple[str | None, Dict[str, Any] | None]:
    m = pat.search(text or "")
    if not m:
        return None, None
    try:
        value = str(m.group(1)).strip()
    except Exception:
        value = None
    if not value:
        return None, None
    start, end = m.span(1)
    lo = max(0, start - 24)
    hi = min(len(text or ""), end + 24)
    snippet = (text or "")[lo:hi]
    provenance = {
        "field": field,
        "source": "ocr_text",
        "start": int(start),
        "end": int(end),
        "snippet": snippet,
        "confidence": float(max(0.0, min(1.0, confidence))),
    }
    return value, provenance


def _extract_all_with_provenance(
    text: str,
    *,
    field: str,
    pat: re.Pattern[str],
    confidence: float,
    limit: int = 5,
) -> tuple[List[str], List[Dict[str, Any]]]:
    values: List[str] = []
    provenance: List[Dict[str, Any]] = []
    for m in pat.finditer(text or ""):
        try:
            val = str(m.group(1)).strip()
        except Exception:
            continue
        if not val:
            continue
        values.append(val)
        start, end = m.span(1)
        lo = max(0, start - 24)
        hi = min(len(text or ""), end + 24)
        provenance.append(
            {
                "field": field,
                "source": "ocr_text",
                "start": int(start),
                "end": int(end),
                "snippet": (text or "")[lo:hi],
                "confidence": float(max(0.0, min(1.0, confidence))),
            }
        )
        if len(values) >= int(limit):
            break
    return values, provenance


def extract_document_schema(text: str) -> Dict[str, Any]:
    t = _norm(text)
    low = t.lower()
    doc_type = "unknown"
    if "bill of lading" in low or re.search(r"\bbol\b|\bb\/l\b", low):
        doc_type = "bol"
    elif "invoice" in low:
        doc_type = "invoice"
    elif "shipping label" in low or "tracking" in low:
        doc_type = "shipping_label"

    invoice_no, p_invoice_no = _extract_with_provenance(
        t, field="invoice.invoice_number", pat=_INV_NO_RE, confidence=0.93
    )
    po_no, p_po_no = _extract_with_provenance(
        t, field="invoice.po_number", pat=_PO_NO_RE, confidence=0.90
    )
    amounts, p_amounts = _extract_all_with_provenance(
        t, field="invoice.amounts", pat=_AMOUNT_RE, confidence=0.82, limit=8
    )
    inv_dates, p_inv_dates = _extract_all_with_provenance(
        t, field="invoice.dates", pat=_DATE_RE, confidence=0.84, limit=8
    )
    invoice = {
        "invoice_number": invoice_no,
        "po_number": po_no,
        "amounts": amounts,
        "dates": inv_dates,
    }
    bol_no, p_bol_no = _extract_with_provenance(
        t, field="bol.bol_number", pat=_BOL_NO_RE, confidence=0.92
    )
    bol_dates, p_bol_dates = _extract_all_with_provenance(
        t, field="bol.dates", pat=_DATE_RE, confidence=0.84, limit=8
    )
    bol_parties: List[str] = []
    p_bol_parties: List[Dict[str, Any]] = []
    for m in _CARRIER_RE.finditer(t):
        try:
            p = str(m.group(2)).strip()
        except Exception:
            continue
        if not p:
            continue
        bol_parties.append(p)
        s, e = m.span(2)
        lo = max(0, s - 24)
        hi = min(len(t), e + 24)
        p_bol_parties.append(
            {
                "field": "bol.parties",
                "source": "ocr_text",
                "start": int(s),
                "end": int(e),
                "snippet": t[lo:hi],
                "confidence": 0.78,
            }
        )
        if len(bol_parties) >= 8:
            break
    bol = {
        "bol_number": bol_no,
        "dates": bol_dates,
        "parties": bol_parties,
    }
    track_no, p_track_no = _extract_with_provenance(
        t, field="shipping_label.tracking_number", pat=_TRACKING_RE, confidence=0.91
    )
    label_dates, p_label_dates = _extract_all_with_provenance(
        t, field="shipping_label.dates", pat=_DATE_RE, confidence=0.84, limit=6
    )
    shipping_label = {
        "tracking_number": track_no,
        "dates": label_dates,
    }

    provenance = [x for x in [
        p_invoice_no,
        p_po_no,
        p_bol_no,
        p_track_no,
    ] if isinstance(x, dict)]
    provenance.extend(p_amounts)
    provenance.extend(p_inv_dates)
    provenance.extend(p_bol_dates)
    provenance.extend(p_bol_parties)
    provenance.extend(p_label_dates)

    by_field_conf: Dict[str, float] = {}
    for p in provenance:
        fld = str(p.get("field") or "")
        conf = float(p.get("confidence") or 0.0)
        if not fld:
            continue
        if fld not in by_field_conf or conf > float(by_field_conf.get(fld) or 0.0):
            by_field_conf[fld] = conf
    if by_field_conf:
        overall = round(sum(by_field_conf.values()) / max(1, len(by_field_conf)), 4)
    else:
        overall = 0.0
    field_values: List[Dict[str, Any]] = []
    for p in provenance:
        field_values.append(
            {
                "field": p.get("field"),
                "value": (t[p.get("start", 0):p.get("end", 0)] if isinstance(p.get("start"), int) and isinstance(p.get("end"), int) else None),
                "confidence": p.get("confidence"),
                "provenance": {
                    "source": p.get("source"),
                    "start": p.get("start"),
                    "end": p.get("end"),
                    "snippet": p.get("snippet"),
                },
            }
        )

    confidence = {
        "overall": overall,
        "by_field": by_field_conf,
    }

    return {
        "doc_type": doc_type,
        "invoice": invoice,
        "bol": bol,
        "shipping_label": shipping_label,
        "confidence": confidence,
        "field_provenance": provenance,
        "fields": field_values,
        "has_structured_fields": bool(
            invoice.get("invoice_number")
            or invoice.get("po_number")
            or bol.get("bol_number")
            or shipping_label.get("tracking_number")
            or invoice.get("amounts")
        ),
    }
