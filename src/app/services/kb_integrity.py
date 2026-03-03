from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path


def _key() -> str:
    return str(os.getenv("KB_SIGNING_KEY", "") or "").strip()


def _sig_path(kb_path: str) -> Path:
    return Path(f"{kb_path}.sig")


def sign_kb_bytes(data: bytes) -> str:
    key = _key()
    if not key:
        return ""
    return hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()


def verify_kb_signature(kb_path: str) -> bool:
    key = _key()
    if not key:
        return True
    p = Path(kb_path)
    sp = _sig_path(kb_path)
    if not p.exists() or not sp.exists():
        return False
    expected = sign_kb_bytes(p.read_bytes())
    actual = (sp.read_text(encoding="utf-8") or "").strip()
    return bool(expected and actual and hmac.compare_digest(expected, actual))


def write_signed_kb(kb_path: str, content: bytes) -> None:
    p = Path(kb_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    sig = sign_kb_bytes(content)
    if sig:
        _sig_path(kb_path).write_text(sig, encoding="utf-8")
