from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Tuple


_WS_RE = re.compile(r"\s+")


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

