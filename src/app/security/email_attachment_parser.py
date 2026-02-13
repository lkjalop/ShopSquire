from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from typing import Any, Dict, List
from xml.etree import ElementTree as ET


_PDF_TEXT_PAT = re.compile(rb"\(([^()]*)\)\s*Tj")
_PRINTABLE_PAT = re.compile(rb"[A-Za-z0-9][A-Za-z0-9 \-_/.:,]{5,}")
_BSB_PAT = re.compile(r"\bBSB[\s:]*([0-9]{3}[- ]?[0-9]{3})", re.IGNORECASE)
_ACC_PAT = re.compile(r"\b(?:account\s*(?:no|number)?)[\s:]*([0-9 ]{6,24})", re.IGNORECASE)
_SWIFT_PAT = re.compile(r"\bSWIFT[\s:]*([A-Z0-9]{8,11})\b", re.IGNORECASE)
_IBAN_PAT = re.compile(r"\bIBAN[\s:]*([A-Z0-9]{12,34})\b", re.IGNORECASE)
_BENEF_PAT = re.compile(r"\b(?:account\s+name|beneficiary|payee)[\s:]*([A-Za-z0-9 .&,'-]{3,80})\b", re.IGNORECASE)


def _decode_b64(raw: str) -> bytes:
    s = str(raw or "").strip()
    if not s:
        return b""
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.b64decode((s + pad).encode("utf-8"), validate=False)


def _extract_zip_xml_text(blob: bytes) -> str:
    out: List[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            targets = [
                n
                for n in zf.namelist()
                if n.endswith(".xml") and (n.startswith("word/") or n.startswith("xl/") or n.startswith("ppt/"))
            ][:24]
            for name in targets:
                try:
                    data = zf.read(name)
                    root = ET.fromstring(data)
                    for node in root.iter():
                        txt = (node.text or "").strip()
                        if txt:
                            out.append(txt)
                except Exception:
                    continue
    except Exception:
        return ""
    return " ".join(out)[:20000]


def _extract_pdf_text(blob: bytes) -> str:
    # Best effort: use installed parser first, then fallback to lightweight pattern extraction.
    try:
        import pypdf  # type: ignore

        r = pypdf.PdfReader(io.BytesIO(blob))
        parts = []
        for p in r.pages[:20]:
            try:
                t = p.extract_text() or ""
                if t:
                    parts.append(t)
            except Exception:
                continue
        if parts:
            return "\n".join(parts)[:20000]
    except Exception:
        pass
    chunks = []
    for m in _PDF_TEXT_PAT.finditer(blob):
        try:
            v = m.group(1).decode("latin-1", errors="ignore").strip()
            if len(v) >= 3:
                chunks.append(v)
        except Exception:
            continue
    if chunks:
        return "\n".join(chunks)[:20000]
    try:
        rough = " ".join([x.decode("latin-1", errors="ignore") for x in _PRINTABLE_PAT.findall(blob)])
        return rough[:20000]
    except Exception:
        return ""

def _pdf_forensics(blob: bytes) -> Dict[str, Any]:
    # Best-effort metadata + suspicious feature counters (no heavy parsing required).
    out: Dict[str, Any] = {
        "producer": None,
        "creator": None,
        "embedded_files_count": 0,
        "objstm_count": 0,
        "xrefstm_present": False,
    }
    try:
        out["embedded_files_count"] = int(blob.count(b"/EmbeddedFile") + blob.count(b"/Filespec"))
    except Exception:
        out["embedded_files_count"] = 0
    try:
        out["objstm_count"] = int(blob.count(b"/ObjStm"))
    except Exception:
        out["objstm_count"] = 0
    try:
        out["xrefstm_present"] = bool(b"/XRefStm" in blob or b"XRefStm" in blob)
    except Exception:
        out["xrefstm_present"] = False
    try:
        import pypdf  # type: ignore

        r = pypdf.PdfReader(io.BytesIO(blob))
        md = getattr(r, "metadata", None)
        if md:
            try:
                out["producer"] = str(getattr(md, "producer", None) or md.get("/Producer") or "") or None
            except Exception:
                pass
            try:
                out["creator"] = str(getattr(md, "creator", None) or md.get("/Creator") or "") or None
            except Exception:
                pass
        try:
            # Prefer pypdf API when available.
            if hasattr(r, "attachments") and isinstance(getattr(r, "attachments"), dict):
                out["embedded_files_count"] = max(out["embedded_files_count"], len(getattr(r, "attachments") or {}))
        except Exception:
            pass
    except Exception:
        pass
    return out


def _try_image_ocr(blob: bytes) -> str:
    # Optional OCR for scanned invoices. Runs only if dependencies are installed.
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        img = Image.open(io.BytesIO(blob))
        txt = pytesseract.image_to_string(img) or ""
        return str(txt)[:20000]
    except Exception:
        return ""


def _extract_bank_fields(text: str) -> Dict[str, Any]:
    t = str(text or "")
    fields: Dict[str, Any] = {}
    m = _BSB_PAT.search(t)
    if m:
        fields["bsb"] = m.group(1).replace(" ", "")
    m = _ACC_PAT.search(t)
    if m:
        fields["account_number"] = re.sub(r"\s+", "", m.group(1))
    m = _SWIFT_PAT.search(t)
    if m:
        fields["swift"] = m.group(1).upper()
    m = _IBAN_PAT.search(t)
    if m:
        fields["iban"] = m.group(1).upper()
    m = _BENEF_PAT.search(t)
    if m:
        fields["beneficiary"] = m.group(1).strip()
    return fields


def _bank_fingerprint(fields: Dict[str, Any]) -> str | None:
    if not isinstance(fields, dict) or not fields:
        return None
    parts = [
        str(fields.get("bsb") or ""),
        str(fields.get("account_number") or ""),
        str(fields.get("swift") or ""),
        str(fields.get("iban") or ""),
        str(fields.get("beneficiary") or ""),
    ]
    parts = [p.strip().lower() for p in parts if p and str(p).strip()]
    if not parts:
        return None
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_text(blob: bytes, *, content_type: str, filename: str) -> str:
    ctype = (content_type or "").lower()
    name = (filename or "").lower()
    if not blob:
        return ""
    if "pdf" in ctype or name.endswith(".pdf"):
        return _extract_pdf_text(blob)
    if (
        "officedocument" in ctype
        or "msword" in ctype
        or "spreadsheet" in ctype
        or name.endswith(".docx")
        or name.endswith(".xlsx")
        or name.endswith(".pptx")
    ):
        return _extract_zip_xml_text(blob)
    if ctype.startswith("text/") or name.endswith(".txt") or name.endswith(".csv") or name.endswith(".md"):
        return blob.decode("utf-8", errors="ignore")[:20000]
    if ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        ocr = _try_image_ocr(blob)
        return ocr[:20000]
    try:
        rough = " ".join([x.decode("latin-1", errors="ignore") for x in _PRINTABLE_PAT.findall(blob)])
        return rough[:20000]
    except Exception:
        return ""


def hydrate_attachments_from_bytes(email: Dict[str, Any]) -> Dict[str, Any]:
    atts = list(email.get("attachments") or [])
    hydrated: List[Dict[str, Any]] = []
    for a in atts:
        row = dict(a or {})
        b64 = row.get("content_b64")
        if not b64:
            hydrated.append(row)
            continue
        blob = b""
        parse_errors: List[str] = []
        try:
            blob = _decode_b64(str(b64))
        except Exception:
            parse_errors.append("base64_decode_failed")
        if blob:
            try:
                row["size_bytes"] = int(row.get("size_bytes") or len(blob))
            except Exception:
                row["size_bytes"] = len(blob)
            try:
                row["sha256"] = str(row.get("sha256") or hashlib.sha256(blob).hexdigest())
            except Exception:
                pass
            try:
                if not row.get("extracted_text"):
                    row["extracted_text"] = _extract_text(
                        blob,
                        content_type=str(row.get("content_type") or ""),
                        filename=str(row.get("name") or ""),
                    )
            except Exception:
                parse_errors.append("text_extract_failed")
            # PDF forensics
            try:
                ctype = str(row.get("content_type") or "").lower()
                name = str(row.get("name") or "").lower()
                if "pdf" in ctype or name.endswith(".pdf"):
                    f = _pdf_forensics(blob)
                    row["pdf_producer"] = f.get("producer")
                    row["pdf_creator"] = f.get("creator")
                    row["embedded_files_count"] = int(f.get("embedded_files_count") or 0)
                    row["pdf_objstm_count"] = int(f.get("objstm_count") or 0)
                    row["pdf_xrefstm_present"] = bool(f.get("xrefstm_present"))
            except Exception:
                pass
            # Explicit bank field extraction + fingerprint
            try:
                bank_fields = _extract_bank_fields(str(row.get("extracted_text") or ""))
                if bank_fields:
                    row["bank_fields"] = bank_fields
                    fp = _bank_fingerprint(bank_fields)
                    if fp:
                        row["extracted_bank_fingerprint"] = fp
            except Exception:
                pass
            # Deterministic structural hashes for drift checks when upstream did not provide them.
            txt = str(row.get("extracted_text") or "")
            if txt and not row.get("template_hash"):
                row["template_hash"] = hashlib.sha256(txt[:2000].encode("utf-8")).hexdigest()[:24]
            if txt and not row.get("layout_hash"):
                layout_sig = f"lines:{txt.count(chr(10))}|digits:{sum(ch.isdigit() for ch in txt)}|upper:{sum(ch.isupper() for ch in txt)}"
                row["layout_hash"] = hashlib.sha256(layout_sig.encode("utf-8")).hexdigest()[:24]
            if not row.get("logo_hash"):
                # Placeholder deterministic hash derived from first bytes for template/logo drift correlation.
                row["logo_hash"] = hashlib.sha256(blob[:4096]).hexdigest()[:24]
            if row.get("compression_artifact_score") is None:
                try:
                    if str(row.get("content_type") or "").lower() in ("image/jpeg", "image/jpg") or str(row.get("name") or "").lower().endswith((".jpg", ".jpeg")):
                        ffda = blob.count(b"\xff\xda")
                        row["compression_artifact_score"] = max(0.0, min(1.0, 0.2 * max(0, ffda - 1)))
                    else:
                        row["compression_artifact_score"] = 0.0
                except Exception:
                    row["compression_artifact_score"] = 0.0
            if row.get("edited_regions") is None:
                row["edited_regions"] = 0
        if parse_errors:
            row["parse_errors"] = parse_errors
        # Never persist raw attachment body in downstream evidence snapshots.
        row.pop("content_b64", None)
        hydrated.append(row)
    email = dict(email)
    email["attachments"] = hydrated
    return email
