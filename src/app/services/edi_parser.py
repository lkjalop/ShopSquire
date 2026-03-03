from __future__ import annotations

import re
from typing import Any, Dict, List


def _split_x12(raw: str) -> List[str]:
    seg_term = "~" if "~" in raw else "\n"
    parts = [p.strip() for p in raw.replace("\r", "\n").split(seg_term)]
    return [p for p in parts if p]


def _split_edifact(raw: str) -> List[str]:
    parts = [p.strip() for p in raw.replace("\r", "\n").split("'")]
    return [p for p in parts if p]


def parse_x12(raw: str) -> Dict[str, Any]:
    segs = _split_x12(raw or "")
    if not segs:
        return {"standard": "x12", "doc_type": "unknown", "segments": 0}
    tx = ""
    for s in segs:
        if s.startswith("ST*"):
            tx = s.split("*")[1] if len(s.split("*")) > 1 else ""
            break
    doc_map = {"850": "purchase_order", "856": "advance_ship_notice", "810": "invoice", "832": "catalog"}
    doc_type = doc_map.get(tx, "unknown")
    out: Dict[str, Any] = {"standard": "x12", "transaction_set": tx, "doc_type": doc_type, "segments": len(segs)}
    items: List[Dict[str, Any]] = []
    ship_to = {}
    for s in segs:
        parts = s.split("*")
        tag = parts[0]
        if tag == "BEG" and len(parts) >= 4:
            out["po_number"] = parts[3]
        elif tag == "BIG" and len(parts) >= 5:
            out["invoice_number"] = parts[2] or parts[4]
        elif tag == "BSN" and len(parts) >= 3:
            out["shipment_id"] = parts[2]
        elif tag == "N1" and len(parts) >= 4 and parts[1] == "ST":
            ship_to = {"name": parts[2], "code": parts[3]}
        elif tag in ("PO1", "IT1", "LIN") and len(parts) >= 3:
            qty = parts[2] if len(parts) >= 3 else None
            sku = ""
            price = None
            for i in range(3, len(parts) - 1):
                if parts[i] in ("VP", "BP", "SK", "IN"):
                    sku = parts[i + 1]
                if parts[i] in ("PE", "PR", "UP"):
                    try:
                        price = float(parts[i + 1])
                    except Exception:
                        price = None
            items.append({"sku": sku, "qty": qty, "price": price})
    if ship_to:
        out["ship_to"] = ship_to
    if items:
        out["items"] = items[:300]
    return out


def parse_edifact(raw: str) -> Dict[str, Any]:
    segs = _split_edifact(raw or "")
    if not segs:
        return {"standard": "edifact", "doc_type": "unknown", "segments": 0}
    doc = "unknown"
    for s in segs:
        if s.startswith("UNH+"):
            parts = s.split("+")
            if len(parts) >= 3:
                typ = parts[2].split(":")[0]
                doc = {"ORDERS": "purchase_order", "DESADV": "advance_ship_notice", "INVOIC": "invoice", "PRICAT": "catalog"}.get(typ, "unknown")
                break
    out: Dict[str, Any] = {"standard": "edifact", "doc_type": doc, "segments": len(segs)}
    items: List[Dict[str, Any]] = []
    for s in segs:
        if s.startswith("BGM+"):
            parts = s.split("+")
            if len(parts) >= 3:
                out["document_number"] = parts[2]
        elif s.startswith("NAD+DP+"):
            out["ship_to"] = {"party": s.split("+")[2]}
        elif s.startswith("LIN+"):
            parts = s.split("+")
            sku = ""
            if len(parts) >= 4 and ":" in parts[3]:
                sku = parts[3].split(":")[0]
            items.append({"sku": sku})
        elif s.startswith("QTY+"):
            m = re.search(r"QTY\+\d+:(\d+)", s)
            if m and items:
                items[-1]["qty"] = int(m.group(1))
        elif s.startswith("PRI+"):
            m = re.search(r"PRI\+\w+:(\d+(?:\.\d+)?)", s)
            if m and items:
                items[-1]["price"] = float(m.group(1))
    if items:
        out["items"] = items[:300]
    return out


def parse_edi_document(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {"standard": "unknown", "doc_type": "unknown", "segments": 0}
    # Fast detection
    if "ISA*" in text or "GS*" in text or "ST*" in text:
        return parse_x12(text)
    if "UNB+" in text or "UNH+" in text:
        return parse_edifact(text)
    return {"standard": "unknown", "doc_type": "unknown", "segments": 0}
