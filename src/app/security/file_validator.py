from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


_MAGIC_HEADERS = {
    "jpeg": [b"\xFF\xD8\xFF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
}

_EOF_MARKERS = {
    "jpeg": b"\xFF\xD9",
    "png": b"IEND\xAE\x42\x60\x82",
    "gif": b"\x3B",
}

_POLYGLOT_SIGNATURES = (
    b"PK\x03\x04",  # zip
    b"MZ",  # pe/exe
    b"<script",
    b"#!/bin/",
)


@dataclass
class FileValidationResult:
    ok: bool = True
    file_type: str = "unknown"
    suspicious: List[str] = field(default_factory=list)
    details: Dict[str, str] = field(default_factory=dict)


def _detect_file_type(blob: bytes) -> str:
    head = blob[:16]
    if any(head.startswith(sig) for sig in _MAGIC_HEADERS["jpeg"]):
        return "jpeg"
    if any(head.startswith(sig) for sig in _MAGIC_HEADERS["png"]):
        return "png"
    if any(head.startswith(sig) for sig in _MAGIC_HEADERS["gif"]):
        return "gif"
    if head.startswith(b"RIFF") and b"WEBP" in blob[:24]:
        return "webp"
    return "unknown"


def validate_image_blob(blob: bytes) -> FileValidationResult:
    """Best-effort image validator for polyglot/malformed uploads.

    This intentionally avoids expensive full parsers in the fast path.
    """
    out = FileValidationResult()
    if not blob:
        out.ok = False
        out.suspicious.append("empty_blob")
        return out

    file_type = _detect_file_type(blob)
    out.file_type = file_type
    if file_type == "unknown":
        out.ok = False
        out.suspicious.append("unknown_magic")
        return out

    eof_marker = _EOF_MARKERS.get(file_type)
    trailing = b""
    if eof_marker:
        end_idx = blob.rfind(eof_marker)
        if end_idx == -1:
            out.suspicious.append("missing_eof_marker")
            out.ok = False
        else:
            trailing = blob[end_idx + len(eof_marker):]
            if trailing.strip(b"\x00\x20\x09\x0A\x0D"):
                out.suspicious.append("trailing_payload_after_eof")

    scan_tail = trailing[:8192] if trailing else blob[:8192]
    for sig in _POLYGLOT_SIGNATURES:
        if sig in scan_tail:
            out.suspicious.append("polyglot_signature_detected")
            break

    out.ok = len(out.suspicious) == 0
    out.details = {
        "file_type": file_type,
        "size_bytes": str(len(blob)),
    }
    return out

