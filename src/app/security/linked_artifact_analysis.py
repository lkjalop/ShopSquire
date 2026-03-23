from __future__ import annotations

import hashlib
import json
import os
import re
from html import unescape
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse
import ipaddress

from src.app.security.email_attachment_parser import _extract_pdf_text, _extract_text, _ocr_pdf_pages, _pdf_forensics
from src.app.security.safe_requests import safe_request


_URL_PAT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_HTML_HREF_PAT = re.compile(r"""(?:href|src)\s*=\s*["']([^"'#>]+)["']""", re.IGNORECASE)
_META_REFRESH_PAT = re.compile(r"""url\s*=\s*['"]?([^'";>\s]+)""", re.IGNORECASE)
_SSN_PAT = re.compile(
    r"\b(\d{3}[-. ]\d{2}[-. ]\d{4})\b"                               # XXX-XX-XXXX, XXX.XX.XXXX, XXX XX XXXX
    r"|\bSSN[\s:#]*([2-9]\d{2}[1-9]\d[1-9]\d{4})\b"                   # SSN: XXXXXXXXX
    r"|\bSocial\s+Security(?:\s+Number)?[\s:#]*(\d{3}[-. ]?\d{2}[-. ]?\d{4})\b",  # Social Security Number: XXX...
    re.IGNORECASE,
)
# Secondary bare 9-digit match (valid SSN range heuristics: area 001-899 excl 666, group/serial nonzero)
_SSN_BARE_PAT = re.compile(r"\b([2-8]\d{2}(?!00)\d{2}(?!0000)\d{4})\b")
_SSN_GLUE_PAT = re.compile(
    r"\b([2-8]\d{2}[-. ]\d{2}[-. ]\d{4})(?=\d?[/.-]\d{1,2}[/.-]\d{2,4}\b)",
    re.IGNORECASE,
)
_CC_PAT = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_DOB_PAT = re.compile(r"\bdate\s+of\s+birth\b", re.IGNORECASE)
_LURE_PATTERNS = [
    re.compile(r"\bpay(?:ment)?\b", re.IGNORECASE),
    re.compile(r"\binvoice\b", re.IGNORECASE),
    re.compile(r"\bwire\b", re.IGNORECASE),
    re.compile(r"\burgent\b", re.IGNORECASE),
    re.compile(r"\bremit(?:tance)?\b", re.IGNORECASE),
]
_SCRIPT_PATTERNS = [
    re.compile(r"/JavaScript|/JS|OpenAction", re.IGNORECASE),
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"\b(?:mshta|powershell|rundll32|regsvr32|certutil)\b", re.IGNORECASE),
]
_ARCHIVE_EXTS = (".zip", ".rar", ".7z", ".iso")
_MACRO_EXTS = (".docm", ".xlsm", ".pptm")
_ARTIFACT_EXTS = (".pdf", ".csv", ".txt", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")
_PDF_INTERNAL_MARKERS = (
    "endobj",
    "stream",
    "startxref",
    "xref",
    "catalog",
    "mediaBox".lower(),
    "fontdescriptor",
    "cidfont",
    "flatedecode",
    "fontfile",
)


_SCANNED_PAGE_PATH_PREFIXES = {"p", "r", "s", "qr"}


def _internal_domain_hints() -> List[str]:
    raw = str(os.getenv("LINKED_ARTIFACT_INTERNAL_DOMAINS") or "").strip()
    hints = [part.strip().lower() for part in raw.split(",") if part.strip()]
    hints.extend(["shopsquire", "localhost"])
    seen: set[str] = set()
    return [hint for hint in hints if hint and not (hint in seen or seen.add(hint))]


def _classify_linked_owner_scope(*, raw_url: str, final_url: str, pii_detected: bool) -> Dict[str, Any]:
    candidate = str(final_url or raw_url or "").strip()
    host = str(urlparse(candidate).hostname or "").strip().lower()
    owner_scope = "unknown"
    owner_reason = "No destination host was available for privacy ownership assessment."
    if host:
        internal_hints = _internal_domain_hints()
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback:
                owner_scope = "likely_internal_platform"
                owner_reason = "The linked destination resolves to a private or loopback address."
            else:
                owner_scope = "external_or_third_party"
                owner_reason = "The linked destination resolves to a public IP address."
        except ValueError:
            if any(host == hint or host.endswith(f".{hint}") or hint in host for hint in internal_hints):
                owner_scope = "likely_internal_platform"
                owner_reason = "The linked destination matches an internal or platform-owned domain hint."
            elif host.endswith((".internal", ".corp", ".local")):
                owner_scope = "likely_internal_platform"
                owner_reason = "The linked destination uses an internal-only naming pattern."
            elif host in {"scanned.page", "www.scanned.page", "qr.scanned.page"}:
                owner_scope = "external_redirect_service"
                owner_reason = "The QR destination is a public redirect service; the underlying document owner still needs human verification."
            else:
                owner_scope = "external_or_third_party"
                owner_reason = "The linked destination appears to be publicly hosted outside platform-owned domain hints."

    exposure_scope = "unknown"
    severity_hint = "medium"
    if pii_detected:
        if owner_scope == "likely_internal_platform":
            exposure_scope = "potential_internal_or_customer_pii"
            severity_hint = "critical"
        elif owner_scope == "external_or_third_party":
            exposure_scope = "potential_external_or_third_party_pii"
            severity_hint = "high"
        elif owner_scope == "external_redirect_service":
            exposure_scope = "redirect_service_to_unknown_owner"
            severity_hint = "high"
        else:
            exposure_scope = "regulated_data_owner_unknown"
            severity_hint = "high"

    return {
        "linked_host": host or None,
        "linked_owner_scope": owner_scope,
        "linked_owner_reason": owner_reason,
        "linked_exposure_scope": exposure_scope,
        "linked_breach_severity_hint": severity_hint,
        "linked_human_verification_required": bool(pii_detected),
        "linked_crisis_management_required": bool(pii_detected),
    }


def _load_offline_fixture_map() -> Dict[str, Any]:
    path = os.path.join("config", "security", "linked_artifact_offline_fixtures.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _offline_fixture_for_url(source_url: str) -> Dict[str, Any] | None:
    data = _load_offline_fixture_map()
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    clean = str(source_url or "").strip()
    if not clean:
        return None
    for row in entries:
        if not isinstance(row, dict):
            continue
        urls = [str(x).strip() for x in (row.get("urls") or []) if str(x).strip()]
        if clean not in urls:
            continue
        rel = str(row.get("local_path") or "").strip()
        if not rel:
            continue
        abs_path = os.path.abspath(rel)
        if not os.path.isfile(abs_path):
            continue
        return {
            "local_path": abs_path,
            "content_type": str(row.get("content_type") or "").strip().lower(),
            "filename": str(row.get("filename") or os.path.basename(abs_path)).strip(),
            "tag": str(row.get("tag") or "").strip(),
        }
    return None


def _provider_candidate_urls(*, source_url: str) -> List[str]:
    """Best-effort provider-specific URL expansion for QR landing pages.

    Some QR SaaS providers serve a SPA shell at the public landing URL and keep
    the actual payload behind a JSON API. When we know the provider shape, fetch
    that metadata passively and surface the real linked artifact instead of
    stopping at index.html.
    """
    parsed = urlparse(source_url)
    host = str(parsed.netloc or "").lower()
    path = str(parsed.path or "").strip("/")
    if host not in {"scanned.page", "www.scanned.page", "qr.scanned.page"}:
        return []

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] not in _SCANNED_PAGE_PATH_PREFIXES:
        return []
    uid = parts[1].strip()
    if not uid:
        return []

    api_candidates = [
        f"{parsed.scheme or 'https'}://{host}/api/qr-code?uId={uid}",
        f"{parsed.scheme or 'https'}://{host}/api/scan/{uid}",
        f"{parsed.scheme or 'https'}://{host}/api/v1/qr/{uid}",
    ]
    data: Any = {}
    for api_url in api_candidates:
        try:
            resp = safe_request("GET", api_url, timeout=6.0, allow_redirects=True)
            if int(getattr(resp, "status_code", 0) or 0) < 400:
                data = resp.json() if hasattr(resp, "json") else {}
                if isinstance(data, dict) and data:
                    break
        except Exception:
            continue

    if not isinstance(data, dict):
        return []
    # Support both {data: {...}} and flat response shapes
    payload: Dict[str, Any] = (data.get("data") if isinstance(data.get("data"), dict) else None) or data
    candidates: List[str] = []
    for key in ("pdf", "pdfUrl", "documentUrl", "fileUrl", "website", "url", "file", "pdfThumbnail"):
        value = str(payload.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            candidates.append(value)
    # Also check nested 'content' dict
    if isinstance(payload.get("content"), dict):
        for key in ("pdf", "url", "fileUrl", "documentUrl"):
            value = str(payload["content"].get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                candidates.append(value)
    return candidates


def _guess_artifact_type(content_type: str, filename: str, blob: bytes) -> str:
    ctype = str(content_type or "").lower()
    name = str(filename or "").lower()
    if "pdf" in ctype or name.endswith(".pdf") or blob.startswith(b"%PDF"):
        return "pdf"
    if "csv" in ctype or name.endswith(".csv"):
        return "csv"
    if "spreadsheet" in ctype or name.endswith((".xlsx", ".xlsm", ".xls")):
        return "xlsx"
    if "zip" in ctype or name.endswith(".zip") or blob.startswith(b"PK\x03\x04"):
        return "zip"
    if "html" in ctype or name.endswith((".html", ".htm")):
        return "html"
    if name.endswith(_MACRO_EXTS):
        return "office_macro_candidate"
    if name.endswith(_ARCHIVE_EXTS):
        return "archive"
    return "unknown"


def _content_disposition_filename(resp_headers: Dict[str, Any]) -> str:
    raw = str(resp_headers.get("content-disposition") or "")
    m = re.search(r'filename="?([^";]+)"?', raw, re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _decode_html_blob(blob: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            text = blob.decode(enc, errors="ignore")
            if text.strip():
                return text
        except Exception:
            continue
    return ""


def _ocr_pdf_text(blob: bytes) -> str:
    return _ocr_pdf_pages(blob, max_pages=3, scale=2.0)


def _pdf_text_looks_unusable(text: str) -> bool:
    sample = str(text or "").strip().lower()
    if not sample:
        return True
    marker_hits = sum(1 for marker in _PDF_INTERNAL_MARKERS if marker in sample)
    return marker_hits >= 3


def _extract_candidate_urls(*, blob: bytes, source_url: str) -> List[str]:
    html = _decode_html_blob(blob)
    if not html:
        return _provider_candidate_urls(source_url=source_url)

    base = source_url
    found: List[str] = []
    found.extend(_provider_candidate_urls(source_url=source_url))
    for abs_url in _URL_PAT.findall(html):
        found.append(unescape(abs_url.strip()))
    for rel_url in _HTML_HREF_PAT.findall(html):
        rel = unescape(str(rel_url or "").strip())
        if rel:
            found.append(urljoin(base, rel))
    m = _META_REFRESH_PAT.search(html)
    if m:
        found.append(urljoin(base, unescape(m.group(1).strip())))

    uniq: List[str] = []
    seen: set[str] = set()
    for url in found:
        clean = str(url or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        uniq.append(clean)

    source_host = str(urlparse(source_url).netloc or "").lower()

    def _score(url: str) -> tuple[int, int, int]:
        parsed = urlparse(url)
        path = str(parsed.path or "").lower()
        query = str(parsed.query or "").lower()
        host = str(parsed.netloc or "").lower()
        artifact_ext = any(path.endswith(ext) for ext in _ARTIFACT_EXTS)
        artifact_hint = any(tok in path or tok in query for tok in ("pdf", "download", "attachment", "export", "file"))
        same_host = host == source_host
        htmlish = path.endswith((".html", ".htm")) or path in {"", "/"}
        return (
            1 if artifact_ext else 0,
            1 if artifact_hint else 0,
            1 if same_host else 0,
        ) if not htmlish else (
            0 if artifact_ext else 0,
            1 if artifact_hint else 0,
            1 if same_host else 0,
        )

    ranked = sorted(uniq, key=_score, reverse=True)
    return ranked[:12]


def _extract_artifact_text(*, artifact_type: str, blob: bytes, content_type: str, filename: str) -> Dict[str, Any]:
    extracted_text = _extract_text(blob, content_type=content_type, filename=filename)
    pdf_forensics = _pdf_forensics(blob) if artifact_type == "pdf" else {}
    pdf_text = _extract_pdf_text(blob) if artifact_type == "pdf" else ""
    ocr_text = ""
    ocr_used = False

    combined_parts = [str(extracted_text or "").strip(), str(pdf_text or "").strip()]
    combined_text = "\n".join(part for part in combined_parts if part).strip()

    if artifact_type == "html" and len(combined_text) < 48:
        html_text = _decode_html_blob(blob)
        if html_text.strip():
            combined_text = html_text

    if artifact_type == "pdf" and (len(combined_text) < 48 or _pdf_text_looks_unusable(combined_text)):
        ocr_text = _ocr_pdf_text(blob)
        if ocr_text.strip():
            ocr_used = True
            combined_text = "\n".join(part for part in [combined_text, ocr_text.strip()] if part).strip()

    return {
        "combined_text": combined_text[:20000],
        "pdf_forensics": pdf_forensics,
        "ocr_used": ocr_used,
        "ocr_text": ocr_text[:20000],
    }


def analyze_linked_artifact(*, url: str, timeout: float = 8.0, max_bytes: int = 2_500_000) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "linked_artifact_available": False,
        "linked_artifact_type": "unknown",
        "linked_content_type": None,
        "linked_filename": None,
        "linked_sha256": None,
        "linked_attack_hypothesis": "unknown_remote_artifact",
        "linked_decode_path": "safe_passive_link_fetch_only",
        "linked_suggested_next_step": "review",
        "pii_detected": False,
        "pii_type": [],
        "ssn_hits": [],
        "embedded_urls": [],
        "linked_text_excerpt": "",
        "linked_pdf_has_javascript": False,
        "linked_redirect_chain": [],
        "linked_ocr_used": False,
    }
    raw_url = str(url or "").strip()
    if not raw_url:
        out["error"] = "linked_url_missing"
        return out
    blob = b""
    content_type = ""
    filename = "artifact"
    final_url = raw_url
    use_offline_fixture = False
    resp = None
    fetch_error = None
    fixture = _offline_fixture_for_url(raw_url)
    if fixture:
        try:
            blob = open(fixture["local_path"], "rb").read()
            content_type = str(fixture.get("content_type") or content_type or "").strip().lower()
            filename = str(fixture.get("filename") or filename or "artifact").strip()
            out["linked_offline_fixture"] = True
            out["linked_offline_fixture_tag"] = fixture.get("tag")
            out["linked_final_url"] = raw_url
            out["linked_redirect_chain"] = [raw_url]
            use_offline_fixture = True
        except Exception:
            blob = b""

    if not blob:
        try:
            resp = safe_request("GET", raw_url, timeout=timeout, allow_redirects=True)
        except Exception as exc:
            fetch_error = f"linked_fetch_failed:{exc}"

        if resp is not None:
            final_url = str(getattr(resp, "url", "") or raw_url)
            out["linked_redirect_chain"] = [raw_url] + ([final_url] if final_url and final_url != raw_url else [])
            out["linked_final_url"] = final_url
            out["linked_http_status"] = int(resp.status_code)
            if int(resp.status_code or 0) < 400:
                blob = bytes(resp.content or b"")
                content_type = str(resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                parsed = urlparse(final_url)
                filename = _content_disposition_filename(resp.headers) or parsed.path.rsplit("/", 1)[-1] or "artifact"

    if (not blob) or (len(blob) > max_bytes) or (resp is not None and int(resp.status_code or 0) >= 400):
        fixture = fixture or _offline_fixture_for_url(raw_url) or _offline_fixture_for_url(final_url)
        if fixture:
            try:
                blob = open(fixture["local_path"], "rb").read()
                content_type = str(fixture.get("content_type") or content_type or "").strip().lower()
                filename = str(fixture.get("filename") or filename or "artifact").strip()
                out["linked_offline_fixture"] = True
                out["linked_offline_fixture_tag"] = fixture.get("tag")
                out["linked_final_url"] = raw_url
                out["linked_redirect_chain"] = [raw_url]
                use_offline_fixture = True
            except Exception:
                pass

    if not blob:
        out["error"] = fetch_error or (f"http_{int(resp.status_code)}" if resp is not None else "linked_artifact_empty")
        return out
    if len(blob) > max_bytes:
        out["error"] = "linked_artifact_too_large"
        out["linked_size_bytes"] = len(blob)
        out["linked_suggested_next_step"] = "queue_sandbox_detonation"
        return out
    if use_offline_fixture and not content_type:
        content_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"

    artifact_type = _guess_artifact_type(content_type, filename, blob)
    text_meta = _extract_artifact_text(
        artifact_type=artifact_type,
        blob=blob,
        content_type=content_type,
        filename=filename,
    )
    combined_text = str(text_meta.get("combined_text") or "").strip()
    pdf_forensics = text_meta.get("pdf_forensics") if isinstance(text_meta.get("pdf_forensics"), dict) else {}
    ocr_used = bool(text_meta.get("ocr_used"))
    embedded_urls = sorted(set(_URL_PAT.findall(combined_text)))[:20]

    if artifact_type == "html":
        candidate_urls = _extract_candidate_urls(blob=blob, source_url=final_url)
        out["linked_embedded_candidates"] = candidate_urls[:10]
        follow_url = next(
            (candidate for candidate in candidate_urls if candidate and candidate.rstrip("/") != final_url.rstrip("/")),
            None,
        )
        if follow_url:
            try:
                resp2 = safe_request("GET", follow_url, timeout=timeout, allow_redirects=True)
                final_url_2 = str(getattr(resp2, "url", "") or follow_url)
                blob2 = bytes(resp2.content or b"")
                if resp2.status_code < 400 and blob2 and len(blob2) <= max_bytes:
                    content_type_2 = str(resp2.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                    parsed_2 = urlparse(final_url_2)
                    filename_2 = _content_disposition_filename(resp2.headers) or parsed_2.path.rsplit("/", 1)[-1] or "artifact"
                    artifact_type_2 = _guess_artifact_type(content_type_2, filename_2, blob2)
                    if artifact_type_2 != "html":
                        out["linked_landing_page_url"] = final_url
                        out["linked_landing_page_excerpt"] = combined_text[:500]
                        final_url = final_url_2
                        content_type = content_type_2
                        filename = filename_2
                        artifact_type = artifact_type_2
                        blob = blob2
                        out["linked_redirect_chain"] = list(dict.fromkeys(out["linked_redirect_chain"] + [follow_url, final_url_2]))
                        text_meta = _extract_artifact_text(
                            artifact_type=artifact_type,
                            blob=blob,
                            content_type=content_type,
                            filename=filename,
                        )
                        combined_text = str(text_meta.get("combined_text") or "").strip()
                        pdf_forensics = text_meta.get("pdf_forensics") if isinstance(text_meta.get("pdf_forensics"), dict) else {}
                        ocr_used = bool(text_meta.get("ocr_used"))
                        embedded_urls = sorted(set(_URL_PAT.findall(combined_text)))[:20]
            except Exception:
                pass

    # SSN detection: try full-pattern first (hyphenated / spaced), then bare 9-digit heuristic
    _ssn_raw = [m for grp in _SSN_PAT.findall(combined_text) for m in (grp if isinstance(grp, tuple) else (grp,)) if m]
    _ssn_glued = _SSN_GLUE_PAT.findall(combined_text)
    _ssn_bare = _SSN_BARE_PAT.findall(combined_text) if not _ssn_raw else []
    ssn_hits = sorted(set(_ssn_raw + _ssn_glued + _ssn_bare))[:20]
    pii_types: List[str] = []
    if ssn_hits:
        pii_types.append("ssn")
    elif "ssn" in combined_text.lower() and _DOB_PAT.search(combined_text):
        pii_types.append("regulated_identity_document")
    if _CC_PAT.search(combined_text):
        pii_types.append("pci")

    attack_hypothesis = "unknown_remote_artifact"
    decode_path = "safe_passive_link_fetch_only"
    suggested_next_step = "review"
    if artifact_type in {"office_macro_candidate", "xlsx"} and filename.lower().endswith(_MACRO_EXTS):
        attack_hypothesis = "linked_macro_artifact"
        decode_path = "sandbox_required_do_not_execute"
        suggested_next_step = "queue_sandbox_detonation"
    elif artifact_type in {"archive", "zip"}:
        attack_hypothesis = "linked_archive_staging"
        decode_path = "sandbox_required_do_not_execute"
        suggested_next_step = "queue_sandbox_detonation"
    elif pii_types:
        attack_hypothesis = "linked_pii_exposure"
        decode_path = "safe_passive_pii_extract"
        suggested_next_step = "review"
    elif any(p.search(combined_text) for p in _LURE_PATTERNS):
        attack_hypothesis = "linked_payment_fraud"
        decode_path = "safe_passive_link_fetch_only"
        suggested_next_step = "review"

    if any(p.search(blob.decode("latin-1", errors="ignore")) for p in _SCRIPT_PATTERNS):
        out["linked_pdf_has_javascript"] = True
        if attack_hypothesis == "unknown_remote_artifact":
            attack_hypothesis = "linked_active_document"
        decode_path = "sandbox_required_do_not_execute"
        suggested_next_step = "queue_sandbox_detonation"

    out.update({
        "linked_artifact_available": True,
        "linked_artifact_type": artifact_type,
        "linked_content_type": content_type or None,
        "linked_filename": filename,
        "linked_sha256": hashlib.sha256(blob).hexdigest(),
        "linked_size_bytes": len(blob),
        "linked_final_url": final_url,
        "linked_attack_hypothesis": attack_hypothesis,
        "linked_decode_path": decode_path,
        "linked_suggested_next_step": suggested_next_step,
        "pii_detected": bool(pii_types),
        "pii_type": pii_types,
        "ssn_hits": ssn_hits,
        "embedded_urls": embedded_urls,
        "linked_text_excerpt": combined_text[:500],
        "linked_pdf_forensics": pdf_forensics,
        "linked_ocr_used": ocr_used,
    })
    out.update(
        _classify_linked_owner_scope(
            raw_url=raw_url,
            final_url=final_url,
            pii_detected=bool(pii_types),
        )
    )
    return out
