from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tarfile
import unicodedata
import zipfile
from typing import Any, Dict, Tuple


_WS_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
_PROMPT_INSTR_RE = re.compile(
    r"(?i)(ignore\s+previous|system\s*prompt|developer\s*mode|jailbreak|execute\s+shell|dump\s+database|export\s+all)"
)
_SCRIPT_RE = re.compile(r"(?i)\b(powershell\s+-enc|cmd\.exe\s+/c|mshta\s+https?://|wscript|cscript|rundll32)\b")

_MAGIC_MIME_PREFIXES = (
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_DEFAULT_DENY_EXT = {
    ".exe",
    ".dll",
    ".com",
    ".scr",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".jse",
    ".wsf",
    ".hta",
    ".msi",
    ".jar",
    ".lnk",
    ".iso",
}
_DEFAULT_ALLOWED_MIME = {
    "application/pdf",
    "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/xml",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/gif",
    "image/avif",
}
_DEFAULT_ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar"}
_DEFAULT_QR_ALLOWLIST = {"localhost", "127.0.0.1"}
_DEFAULT_ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/gif",
    "image/avif",
}
_EXT_MIME_EXPECTED = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".gif": {"image/gif"},
    ".bmp": {"image/bmp"},
    ".tif": {"image/tiff"},
    ".tiff": {"image/tiff"},
    ".webp": {"image/webp"},
    ".avif": {"image/avif"},
}


def _env_list(name: str, default: set[str]) -> set[str]:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return set(default)
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or default).strip())
    except Exception:
        return int(default)


def _safe_b64decode(raw: str | None) -> bytes:
    s = str(raw or "").strip()
    if not s:
        return b""
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    pad = "=" * ((4 - len(s) % 4) % 4)
    try:
        return base64.b64decode((s + pad).encode("utf-8"), validate=False)
    except Exception:
        return b""


def _ext(name: str | None) -> str:
    v = str(name or "").strip().lower()
    if "." not in v:
        return ""
    return "." + v.rsplit(".", 1)[-1]


def _sniff_mime(blob: bytes) -> str | None:
    if not blob:
        return None
    for magic, mime in _MAGIC_MIME_PREFIXES:
        if blob.startswith(magic):
            return mime
    # WebP: starts with RIFF + 4-byte size + WEBP signature at offset 8
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    # AVIF uses the ISO BMFF container with an `ftypavif`/`ftypavis` brand.
    if len(blob) >= 16 and blob[4:8] == b"ftyp" and blob[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def _detect_polyglot_signatures(blob: bytes, *, primary_mime: str | None) -> list[str]:
    if not blob:
        return []
    hits: list[str] = []
    window = blob[:4096]
    for magic, mime in _MAGIC_MIME_PREFIXES:
        if primary_mime and mime == primary_mime and window.startswith(magic):
            continue
        try:
            if window.find(magic, 1) >= 0:
                hits.append(mime)
        except Exception:
            continue
    uniq = []
    for h in hits:
        if h not in uniq:
            uniq.append(h)
    return uniq[:5]


def _mime_allowed(mime: str | None, allowed: set[str]) -> bool:
    m = str(mime or "").strip().lower()
    if not m:
        return True
    if m in allowed:
        return True
    if m.startswith("image/") and "image/*" in allowed:
        return True
    if m.startswith("text/") and "text/*" in allowed:
        return True
    return False


def _archive_inspect(
    blob: bytes,
    *,
    filename: str,
    deny_ext: set[str],
    max_entries: int,
    max_member_bytes: int,
    max_ratio: float,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "archive": True,
        "archive_type": None,
        "blocked": False,
        "reasons": [],
        "member_count": 0,
        "members": [],
    }
    name = str(filename or "").lower()
    is_zip = bool(blob.startswith(b"PK\x03\x04")) or name.endswith(".zip")
    is_tar = (name.endswith(".tar") or name.endswith(".tgz") or name.endswith(".gz") or name.endswith(".bz2"))
    if not is_zip and not is_tar:
        out["archive"] = False
        return out

    try:
        if is_zip:
            out["archive_type"] = "zip"
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                infos = zf.infolist()
                out["member_count"] = len(infos)
                total_comp = 0
                total_uncomp = 0
                for info in infos[: max_entries + 1]:
                    fn = str(info.filename or "")
                    out["members"].append(fn)
                    total_comp += int(info.compress_size or 0)
                    total_uncomp += int(info.file_size or 0)
                    if _ext(fn) in deny_ext:
                        out["blocked"] = True
                        out["reasons"].append("archive_contains_executable")
                    if int(info.file_size or 0) > max_member_bytes:
                        out["blocked"] = True
                        out["reasons"].append("archive_member_too_large")
                    if (int(info.flag_bits or 0) & 0x1) != 0:
                        out["blocked"] = True
                        out["reasons"].append("archive_encrypted")
                if len(infos) > max_entries:
                    out["blocked"] = True
                    out["reasons"].append("archive_too_many_entries")
                ratio = float(total_uncomp) / float(max(1, total_comp))
                out["compression_ratio"] = round(ratio, 3)
                if ratio > max_ratio:
                    out["blocked"] = True
                    out["reasons"].append("archive_zip_bomb_ratio")
        else:
            out["archive_type"] = "tar"
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
                members = tf.getmembers()
                out["member_count"] = len(members)
                for m in members[: max_entries + 1]:
                    fn = str(m.name or "")
                    out["members"].append(fn)
                    if _ext(fn) in deny_ext:
                        out["blocked"] = True
                        out["reasons"].append("archive_contains_executable")
                    if int(m.size or 0) > max_member_bytes:
                        out["blocked"] = True
                        out["reasons"].append("archive_member_too_large")
                if len(members) > max_entries:
                    out["blocked"] = True
                    out["reasons"].append("archive_too_many_entries")
    except Exception:
        out["blocked"] = True
        out["reasons"].append("archive_parse_failed")

    out["reasons"] = sorted(set([str(r) for r in (out.get("reasons") or []) if r]))
    out["members"] = (out.get("members") or [])[:20]
    return out


def _av_scan(blob: bytes, *, filename: str, mime: str | None) -> Dict[str, Any]:
    enabled = str(os.getenv("ATTACHMENT_AV_ENABLED", "1")).strip().lower() in ("1", "true", "yes")
    if not enabled or not blob:
        return {"enabled": enabled, "provider": "disabled", "malicious": False, "signature": None}

    # Optional clamd path first (cheap when available), then deterministic fallback.
    host = str(os.getenv("CLAMAV_HOST") or "127.0.0.1").strip()
    port = _env_int("CLAMAV_PORT", 3310)
    try:
        import clamd  # type: ignore

        cd = clamd.ClamdNetworkSocket(host=host, port=port, timeout=2.5)
        res = cd.instream(io.BytesIO(blob))
        sig = None
        status = ""
        if isinstance(res, dict):
            rec = res.get("stream")
            if isinstance(rec, tuple):
                status = str(rec[0] or "")
                sig = str(rec[1] or "") if len(rec) > 1 else None
        mal = status.upper() == "FOUND"
        return {"enabled": True, "provider": "clamd", "malicious": bool(mal), "signature": sig}
    except Exception:
        pass

    text_probe = ""
    try:
        text_probe = blob[:200000].decode("utf-8", errors="ignore")
    except Exception:
        text_probe = ""
    low = text_probe.lower()
    name = str(filename or "").lower()
    m = str(mime or "").lower()
    signatures = []
    if _SCRIPT_RE.search(low):
        signatures.append("script_exec_pattern")
    if "autoopen" in low or "vbasignature" in low or "createobject(\"wscript.shell\")" in low:
        signatures.append("macro_exec_pattern")
    if _ext(name) in _DEFAULT_DENY_EXT:
        signatures.append("deny_extension")
    if m in ("application/x-dosexec", "application/x-msdownload"):
        signatures.append("executable_mime")
    return {
        "enabled": True,
        "provider": "heuristic",
        "malicious": bool(signatures),
        "signature": signatures[0] if signatures else None,
        "matches": signatures[:5],
    }


def _nfkc(s: str) -> str:
    try:
        return unicodedata.normalize("NFKC", s)
    except Exception:
        return s


def _clean_text(s: str, *, max_len: int = 200_000) -> str:
    # This is intentionally "intake only": normalize + trim. No scoring/routing here.
    s = str(s or "")
    s = s.replace("\x00", "")
    s = _nfkc(s)
    s = s.strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s


def normalize_email_intake(email: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (normalized_email, intake_meta).

    No detection logic. Only normalization/sanitization suitable for a dedicated intake gate.
    """
    src = dict(email or {})
    out = dict(src)
    changes = []

    def _set(k: str, v: Any, *, max_len: int = 50_000) -> None:
        nonlocal out, changes
        before = out.get(k)
        after = _clean_text(v, max_len=max_len)
        out[k] = after
        try:
            if str(before or "") != after:
                changes.append(k)
        except Exception:
            pass

    _set("message_id", src.get("message_id"), max_len=500)
    _set("from_addr", src.get("from_addr"), max_len=2000)
    _set("reply_to", src.get("reply_to"), max_len=2000)
    _set("subject", src.get("subject"), max_len=10_000)
    _set("body", src.get("body"), max_len=200_000)

    # Light whitespace canonicalization for fields that are commonly diffed.
    try:
        for k in ("subject", "from_addr", "reply_to"):
            v = out.get(k)
            if isinstance(v, str):
                out[k] = _WS_RE.sub(" ", v).strip()
    except Exception:
        pass

    # Keep attachments as-is; attachment parsing/bytes hydration happens downstream.
    meta = {
        "gate": "intake_only",
        "unicode_nfkc_applied": True,
        "changed_fields": sorted(set([c for c in changes if c])),
    }
    return out, meta


def normalize_text_intake(payload: Dict[str, Any], *, keys: Tuple[str, ...]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    src = dict(payload or {})
    out = dict(src)
    changes = []
    for k in keys:
        before = out.get(k)
        after = _clean_text(out.get(k), max_len=200_000)
        out[k] = after
        try:
            if str(before or "") != after:
                changes.append(k)
        except Exception:
            pass
    meta = {"gate": "intake_only", "unicode_nfkc_applied": True, "changed_fields": sorted(set(changes))}
    return out, meta


def sanitize_ocr_text(text: str, *, max_len: int = 40_000) -> Tuple[str, Dict[str, Any]]:
    raw = _clean_text(text, max_len=max_len)
    flags = []
    removed = 0
    cleaned = raw
    for m in _PROMPT_INSTR_RE.findall(raw):
        if m:
            removed += 1
    try:
        if _PROMPT_INSTR_RE.search(raw):
            flags.append("prompt_instruction_present")
            cleaned = _PROMPT_INSTR_RE.sub("[REMOVED_UNTRUSTED_INSTRUCTION]", raw)
    except Exception:
        cleaned = raw
    if cleaned != raw:
        flags.append("ocr_text_sanitized")
    return cleaned, {
        "changed": cleaned != raw,
        "removed_instruction_hits": int(removed),
        "flags": flags,
        "text_hash": hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16] if cleaned else None,
    }


def enforce_qr_url_allowlist(urls: list[str], *, allowlist: set[str] | None = None) -> Dict[str, Any]:
    allowed_hosts = set([x.lower() for x in (allowlist or _env_list("QR_URL_ALLOWLIST", _DEFAULT_QR_ALLOWLIST)) if x])
    allowed = []
    blocked = []
    for u in urls or []:
        url = str(u or "").strip()
        if not url:
            continue
        host = ""
        try:
            from urllib.parse import urlparse

            host = str(urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        ok = bool(host and any(host == h or host.endswith("." + h) for h in allowed_hosts))
        if ok:
            allowed.append(url)
        else:
            blocked.append({"url": url, "host": host or None, "reason": "qr_url_not_allowlisted"})
    return {
        "allowlist": sorted(allowed_hosts),
        "allowed": allowed[:20],
        "blocked": blocked[:20],
        "blocked_count": len(blocked),
    }


def sanitize_attachment_ocr_for_llm(email: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    out = dict(email or {})
    atts = [dict(a or {}) for a in (out.get("attachments") or [])]
    changed = 0
    prompt_hits = 0
    blocked_urls: list[dict[str, Any]] = []
    for row in atts:
        txt = str(row.get("extracted_text") or row.get("ocr_text") or "")
        if not txt:
            continue
        sanitized, meta = sanitize_ocr_text(txt)
        if bool(meta.get("changed")):
            changed += 1
            row["extracted_text"] = sanitized
            row["ocr_sanitization"] = meta
        prompt_hits += int(meta.get("removed_instruction_hits") or 0)
        urls = [m.group(0) for m in _URL_RE.finditer(sanitized)]
        if urls:
            policy = enforce_qr_url_allowlist(urls)
            row["qr_url_policy"] = policy
            if int(policy.get("blocked_count") or 0) > 0:
                blocked_urls.extend(list(policy.get("blocked") or []))
    out["attachments"] = atts
    return out, {
        "gate": "ocr_qr_sanitization",
        "changed_attachments": int(changed),
        "prompt_instruction_hits": int(prompt_hits),
        "blocked_qr_urls": blocked_urls[:20],
        "blocked_qr_url_count": len(blocked_urls),
    }


def _evaluate_binary_ingest(
    *,
    filename: str,
    content_type: str | None,
    blob: bytes,
    size_bytes: int | None,
    deny_ext: set[str],
    allowed_mime: set[str],
    archive_ext: set[str],
    max_bytes: int,
    max_entries: int,
    max_member_bytes: int,
    max_ratio: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any] | None, Dict[str, Any] | None]:
    name = str(filename or "").strip() or "upload"
    declared_mime = str(content_type or "").strip().lower() or None
    data = bytes(blob or b"")
    sz = int(size_bytes or len(data))
    file_ext = _ext(name)
    sniff_magic = _sniff_mime(data)
    sniff = sniff_magic or declared_mime
    reasons: list[str] = []
    if file_ext in deny_ext:
        reasons.append("denied_extension")
    if sz > max_bytes:
        reasons.append("attachment_too_large")
    if not _mime_allowed(sniff, allowed_mime):
        reasons.append("mime_not_allowed")
    # Block content-type spoofing for image uploads when no valid image magic header exists.
    if declared_mime and str(declared_mime).startswith("image/") and not sniff_magic:
        reasons.append("image_magic_header_missing")
    try:
        expected = _EXT_MIME_EXPECTED.get(file_ext) or set()
        if expected and sniff and str(sniff).lower() not in expected:
            reasons.append("filename_mime_mismatch")
    except Exception:
        pass
    polyglot_hits = _detect_polyglot_signatures(data, primary_mime=sniff)
    if polyglot_hits and str(os.getenv("ATTACHMENT_POLYGLOT_BLOCK", "1")).strip().lower() in ("1", "true", "yes"):
        reasons.append("polyglot_signature_detected")

    archive_meta: Dict[str, Any] | None = None
    if data and (file_ext in archive_ext or str(sniff or "").endswith("/zip") or str(sniff or "") == "application/zip"):
        archive_meta = _archive_inspect(
            data,
            filename=name,
            deny_ext=deny_ext,
            max_entries=max_entries,
            max_member_bytes=max_member_bytes,
            max_ratio=max_ratio,
        )
        if bool(archive_meta.get("blocked")):
            reasons.extend(list(archive_meta.get("reasons") or []))

    av_meta: Dict[str, Any] | None = None
    if data:
        av_meta = _av_scan(data, filename=name, mime=sniff)
        if bool((av_meta or {}).get("malicious")):
            reasons.append("av_malicious")

    ingest_gate = {
        "size_bytes": sz,
        "content_type_declared": declared_mime,
        "content_type_sniffed": sniff,
        "ext": file_ext,
        "polyglot_hits": polyglot_hits,
        "status": "blocked" if reasons else "accepted",
        "reasons": sorted(set(reasons)),
    }
    return ingest_gate, {"name": name, "content_type": declared_mime}, archive_meta, av_meta


def strict_binary_ingest_gate(
    *,
    filename: str,
    content_type: str | None,
    blob: bytes,
    size_bytes: int | None = None,
    allowed_mime_override: set[str] | None = None,
) -> Dict[str, Any]:
    """Strict ingest controls for a single uploaded binary (CV/storefront uploads)."""
    deny_ext = _env_list("ATTACHMENT_DENY_EXT", _DEFAULT_DENY_EXT)
    allowed_mime = set(allowed_mime_override or _env_list("ATTACHMENT_ALLOWED_MIME", _DEFAULT_ALLOWED_MIME))
    archive_ext = _env_list("ATTACHMENT_ARCHIVE_EXT", _DEFAULT_ARCHIVE_EXT)
    max_bytes = _env_int("ATTACHMENT_MAX_BYTES", 12 * 1024 * 1024)
    max_entries = _env_int("ATTACHMENT_ARCHIVE_MAX_ENTRIES", 200)
    max_member_bytes = _env_int("ATTACHMENT_ARCHIVE_MEMBER_MAX_BYTES", 10 * 1024 * 1024)
    max_ratio = float(os.getenv("ATTACHMENT_ARCHIVE_MAX_RATIO", "80") or 80.0)

    ingest_gate, row_meta, archive_meta, av_meta = _evaluate_binary_ingest(
        filename=filename,
        content_type=content_type,
        blob=blob,
        size_bytes=size_bytes,
        deny_ext=deny_ext,
        allowed_mime=allowed_mime,
        archive_ext=archive_ext,
        max_bytes=max_bytes,
        max_entries=max_entries,
        max_member_bytes=max_member_bytes,
        max_ratio=max_ratio,
    )
    blocked = str(ingest_gate.get("status") or "") == "blocked"
    return {
        "gate": "strict_binary_ingest",
        "blocked": bool(blocked),
        "block_reasons": list(ingest_gate.get("reasons") or []),
        "filename": row_meta.get("name"),
        "ingest_gate": ingest_gate,
        "archive_inspection": archive_meta,
        "av_scan": av_meta,
        "limits": {
            "max_bytes": max_bytes,
            "archive_max_entries": max_entries,
            "archive_max_ratio": max_ratio,
        },
    }


def strict_image_ingest_gate(
    *,
    filename: str,
    content_type: str | None,
    blob: bytes,
    size_bytes: int | None = None,
) -> Dict[str, Any]:
    allowed_image = _env_list("IMAGE_ALLOWED_MIME", _DEFAULT_ALLOWED_IMAGE_MIME)
    out = strict_binary_ingest_gate(
        filename=filename,
        content_type=content_type,
        blob=blob,
        size_bytes=size_bytes,
        allowed_mime_override=allowed_image,
    )
    try:
        out["gate"] = "strict_image_ingest"
    except Exception:
        pass
    return out


def strict_attachment_ingest_gate(email: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Strict ingest controls for attachment intake before deeper parsing/LLM use."""
    src = dict(email or {})
    atts = [dict(a or {}) for a in (src.get("attachments") or [])]
    deny_ext = _env_list("ATTACHMENT_DENY_EXT", _DEFAULT_DENY_EXT)
    allowed_mime = _env_list("ATTACHMENT_ALLOWED_MIME", _DEFAULT_ALLOWED_MIME)
    archive_ext = _env_list("ATTACHMENT_ARCHIVE_EXT", _DEFAULT_ARCHIVE_EXT)
    max_attachments = _env_int("ATTACHMENT_MAX_COUNT", 16)
    max_bytes = _env_int("ATTACHMENT_MAX_BYTES", 12 * 1024 * 1024)
    max_total = _env_int("ATTACHMENT_MAX_TOTAL_BYTES", 30 * 1024 * 1024)
    max_entries = _env_int("ATTACHMENT_ARCHIVE_MAX_ENTRIES", 200)
    max_member_bytes = _env_int("ATTACHMENT_ARCHIVE_MEMBER_MAX_BYTES", 10 * 1024 * 1024)
    max_ratio = float(os.getenv("ATTACHMENT_ARCHIVE_MAX_RATIO", "80") or 80.0)

    total = 0
    blocked_count = 0
    global_reasons: list[str] = []
    overflow = max(0, len(atts) - max_attachments)
    if overflow > 0:
        global_reasons.append("too_many_attachments")

    out_atts = []
    for idx, row in enumerate(atts):
        name = str(row.get("name") or f"attachment_{idx}")
        if idx >= max_attachments:
            row["ingest_gate"] = {
                "size_bytes": int(row.get("size_bytes") or 0),
                "content_type_declared": str(row.get("content_type") or "").strip().lower() or None,
                "content_type_sniffed": None,
                "ext": _ext(name),
                "status": "blocked",
                "reasons": ["too_many_attachments"],
            }
            blocked_count += 1
            out_atts.append(row)
            continue
        blob = _safe_b64decode(row.get("content_b64"))
        sz = int(row.get("size_bytes") or len(blob or b""))
        total += max(0, sz)
        ingest_gate, _row_meta, archive_meta, av_meta = _evaluate_binary_ingest(
            filename=name,
            content_type=row.get("content_type"),
            blob=blob,
            size_bytes=sz,
            deny_ext=deny_ext,
            allowed_mime=allowed_mime,
            archive_ext=archive_ext,
            max_bytes=max_bytes,
            max_entries=max_entries,
            max_member_bytes=max_member_bytes,
            max_ratio=max_ratio,
        )
        if archive_meta is not None:
            row["archive_inspection"] = archive_meta
        if av_meta is not None:
            row["av_scan"] = av_meta
        row["ingest_gate"] = ingest_gate
        if str((ingest_gate or {}).get("status") or "") == "blocked":
            blocked_count += 1
        out_atts.append(row)

    if total > max_total:
        global_reasons.append("total_attachment_size_exceeded")
    src["attachments"] = out_atts
    blocked = bool(blocked_count > 0 or global_reasons)
    return src, {
        "gate": "strict_attachment_ingest",
        "blocked": blocked,
        "blocked_count": blocked_count,
        "accepted_count": max(0, len(out_atts) - blocked_count),
        "attachment_count": len(out_atts),
        "total_size_bytes": int(total),
        "global_reasons": sorted(set(global_reasons)),
        "block_reasons": sorted(set(global_reasons + (["attachment_blocked"] if blocked_count > 0 else []))),
        "limits": {
            "max_attachments": max_attachments,
            "max_bytes": max_bytes,
            "max_total": max_total,
            "archive_max_entries": max_entries,
            "archive_max_ratio": max_ratio,
        },
    }
