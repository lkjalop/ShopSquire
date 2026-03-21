from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from typing import Any, Dict, List
from xml.etree import ElementTree as ET


_PDF_TEXT_PAT = re.compile(rb"\(([^()]*)\)\s*Tj")
_PDF_URI_PAT = re.compile(rb"/URI\s*\(([^)]{4,512})\)")
_PRINTABLE_PAT = re.compile(rb"[A-Za-z0-9][A-Za-z0-9 \-_/.:,]{5,}")
_BSB_PAT = re.compile(r"\bBSB[\s:]*([0-9]{3}[- ]?[0-9]{3})", re.IGNORECASE)
_ACC_PAT = re.compile(r"\b(?:account\s*(?:no|number)?)[\s:]*([0-9 -]{6,24})", re.IGNORECASE)
_SWIFT_PAT = re.compile(r"\bSWIFT[\s:]*([A-Z0-9]{8,11})\b", re.IGNORECASE)
_IBAN_PAT = re.compile(r"\bIBAN[\s:]*([A-Z0-9]{12,34})\b", re.IGNORECASE)
_BENEF_PAT = re.compile(r"\b(?:account\s+name|beneficiary|payee)[\s:]*([A-Za-z0-9 .&,'-]{3,80})\b", re.IGNORECASE)
_PAYMENT_HINT_PAT = re.compile(
    r"(?i)\b("
    r"bank(?:ing)?\s+details?"
    r"|remittance"
    r"|payment"
    r"|bsb"
    r"|swift"
    r"|iban"
    r"|beneficiary"
    r"|payee"
    r"|account(?:\s+name|\s+number|\s+no)?"
    r"|invoice"
    r"|abn"
    r"|updated\s+payment\s+details?"
    r"|bank(?:ing)?\s+details?\s+have\s+changed"
    r")\b"
)


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


def _dedupe_text_blocks(parts: List[str]) -> str:
    out: List[str] = []
    seen: set[str] = set()
    for part in parts:
        for line in re.split(r"[\r\n]+", str(part or "")):
            cleaned = re.sub(r"\s+", " ", line).strip()
            if len(cleaned) < 2:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(cleaned)
    return "\n".join(out)[:20000]


def _extract_pdf_text_basic(blob: bytes) -> str:
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


def _extract_pdf_urls(blob: bytes) -> List[str]:
    urls: List[str] = []
    for match in _PDF_URI_PAT.finditer(blob):
        try:
            url = match.group(1).decode("latin-1", errors="ignore").strip()
            if url and url not in urls:
                urls.append(url)
        except Exception:
            continue
    try:
        rough = " ".join([x.decode("latin-1", errors="ignore") for x in _PRINTABLE_PAT.findall(blob)])
        for url in re.findall(r"https?://[^\s<>'\"`]+", rough, re.IGNORECASE):
            if url not in urls:
                urls.append(url)
    except Exception:
        pass
    return urls[:12]


def _pdf_text_looks_unusable(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) < 80:
        return True
    alpha_count = sum(ch.isalpha() for ch in cleaned)
    if alpha_count < 25:
        return True
    pdf_syntax_hits = 0
    for tok in (" obj ", " endobj", " stream", " endstream", "/type", "/font", "/page", "/catalog", "reportlab generated pdf", "%%eof", "xref"):
        if tok in cleaned.lower():
            pdf_syntax_hits += 1
    if pdf_syntax_hits >= 4 and len(_PAYMENT_HINT_PAT.findall(cleaned)) == 0:
        return True
    hint_count = len(_PAYMENT_HINT_PAT.findall(cleaned))
    return hint_count == 0 and len(cleaned.split()) < 24


def _extract_pdf_text(blob: bytes) -> str:
    primary = _extract_pdf_text_basic(blob)
    parts: List[str] = [primary] if str(primary or "").strip() else []
    if _pdf_text_looks_unusable(primary):
        ocr_text = _ocr_pdf_pages(blob, max_pages=4, scale=2.2)
        if str(ocr_text or "").strip():
            parts.append(ocr_text)
    urls = _extract_pdf_urls(blob)
    if urls:
        parts.append("\n".join(urls))
    return _dedupe_text_blocks(parts)

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


def _preview_png_b64(blob: bytes, *, content_type: str, filename: str, max_side: int = 320) -> str | None:
    try:
        from PIL import Image  # type: ignore

        ctype = str(content_type or "").lower()
        name = str(filename or "").lower()
        img = None
        if ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
            img = Image.open(io.BytesIO(blob))
        elif "pdf" in ctype or name.endswith(".pdf"):
            try:
                import pypdfium2 as pdfium  # type: ignore

                pdf = pdfium.PdfDocument(blob)
                if len(pdf) > 0:
                    page = pdf[0]
                    bitmap = page.render(scale=1.5)
                    img = bitmap.to_pil()
            except Exception:
                img = None
        if img is None:
            return None
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        return None


def _ocr_pdf_pages(blob: bytes, *, max_pages: int = 3, scale: float = 2.0) -> str:
    """Rasterize PDF pages and OCR them.

    Prefers pypdfium2 because it is lightweight and works well in the current
    Windows dev environment without requiring external poppler/ghostscript.
    """
    texts: List[str] = []

    try:
        import pypdfium2 as pdfium  # type: ignore

        pdf = pdfium.PdfDocument(blob)
        page_count = min(len(pdf), max_pages)
        for idx in range(page_count):
            try:
                page = pdf[idx]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                out = io.BytesIO()
                pil_image.save(out, format="PNG")
                txt = _try_image_ocr(out.getvalue())
                if txt.strip():
                    texts.append(txt.strip())
            except Exception:
                continue
        if texts:
            return "\n".join(texts)[:20000]
    except Exception:
        pass

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


def _get_steg_threshold(tenant_id: str | None = None) -> float | None:
    """Return per-tenant steg sensitivity threshold, or None for global default."""
    if not tenant_id:
        return None
    try:
        from src.app.security.threshold_tuning import get_runtime_thresholds  # type: ignore
        rt = get_runtime_thresholds(tenant_id)
        v = rt.get("steg_threshold") or rt.get("steg_sensitivity_threshold")
        return float(v) if v is not None else None
    except Exception:
        return None


def _scan_pdf_images_steg(
    blob: bytes,
    *,
    threshold: float | None = None,
) -> "Any | None":
    """Extract embedded images from a PDF and run steg analysis on each.

    Returns the first suspicious StegResult found, or None if all clean.
    Works with pypdf's page.images API (pypdf >= 3.4).  Falls back silently
    when pypdf is unavailable or the PDF has no extractable raster images.
    """
    try:
        import pypdf  # type: ignore
        from PIL import Image as _PImage  # type: ignore
        from src.app.security.steg_detector import detect_steganography  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(blob))
        for page in reader.pages[:5]:
            images = getattr(page, "images", None) or []
            for img_obj in images:
                try:
                    img_data = getattr(img_obj, "data", None) or b""
                    if not img_data:
                        continue
                    pil_img = _PImage.open(io.BytesIO(img_data)).convert("RGB")
                    out_buf = io.BytesIO()
                    pil_img.save(out_buf, format="PNG")
                    result = detect_steganography(out_buf.getvalue(), threshold=threshold)
                    if result.is_suspicious:
                        return result
                except Exception:
                    continue
    except Exception:
        pass
    return None


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


def hydrate_attachments_from_bytes(
    email: Dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
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
                    row["pdf_embedded_urls"] = _extract_pdf_urls(blob)
            except Exception:
                pass
            # Explicit bank field extraction + fingerprint
            try:
                bank_fields = _extract_bank_fields(str(row.get("extracted_text") or ""))
                if bank_fields:
                    row["bank_fields"] = bank_fields
                    if bank_fields.get("beneficiary") and not row.get("extracted_account_name"):
                        row["extracted_account_name"] = str(bank_fields.get("beneficiary") or "")
                    fp = _bank_fingerprint(bank_fields)
                    if fp:
                        row["extracted_bank_fingerprint"] = fp
            except Exception:
                pass
            try:
                preview_b64 = _preview_png_b64(
                    blob,
                    content_type=str(row.get("content_type") or ""),
                    filename=str(row.get("name") or ""),
                )
                if preview_b64:
                    row["preview_png_b64"] = preview_b64
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
            # ── Steganographic analysis — image attachments + CID inline images ──
            try:
                _ctype = str(row.get("content_type") or "").lower()
                _name = str(row.get("name") or "").lower()
                _is_img = _ctype.startswith("image/") or _name.endswith(
                    (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
                )
                if _is_img and row.get("steg_score") is None:
                    from src.app.security.steg_detector import detect_steganography as _detect_steg  # type: ignore
                    _thr = _get_steg_threshold(tenant_id)
                    _steg = _detect_steg(blob, threshold=_thr)
                    row["steg_score"] = round(float(_steg.steg_score), 4)
                    row["steg_suspicious"] = bool(_steg.is_suspicious)
                    if _steg.is_suspicious:
                        row["steg_explanations"] = list(_steg.explanations)[:8]
                        row["steg_details"] = dict(_steg.details or {})
                        row["steg_signals"] = {
                            "lsb_entropy_r": round(float(_steg.lsb_entropy_r), 4),
                            "lsb_entropy_g": round(float(_steg.lsb_entropy_g), 4),
                            "lsb_entropy_b": round(float(_steg.lsb_entropy_b), 4),
                            "chi_square_p": round(float(_steg.chi_square_p), 4),
                            "spa_estimate": round(float(_steg.spa_estimate), 4),
                        }
            except Exception:
                pass
            # ── Steganographic analysis — PDF embedded images ──
            try:
                _ctype_pdf = str(row.get("content_type") or "").lower()
                _name_pdf = str(row.get("name") or "").lower()
                if ("pdf" in _ctype_pdf or _name_pdf.endswith(".pdf")) and row.get("steg_score") is None:
                    _thr_pdf = _get_steg_threshold(tenant_id)
                    _steg_pdf = _scan_pdf_images_steg(blob, threshold=_thr_pdf)
                    if _steg_pdf is not None:
                        row["steg_score"] = round(float(_steg_pdf.steg_score), 4)
                        row["steg_suspicious"] = bool(_steg_pdf.is_suspicious)
                        row["steg_source"] = "pdf_embedded_image"
                        if _steg_pdf.is_suspicious:
                            row["steg_explanations"] = list(_steg_pdf.explanations)[:8]
                            row["steg_details"] = dict(_steg_pdf.details or {})
                    else:
                        row.setdefault("steg_score", 0.0)
                        row.setdefault("steg_suspicious", False)
            except Exception:
                pass
        if parse_errors:
            row["parse_errors"] = parse_errors
        # Never persist raw attachment body in downstream evidence snapshots.
        row.pop("content_b64", None)
        hydrated.append(row)
    email = dict(email)
    email["attachments"] = hydrated
    return email
