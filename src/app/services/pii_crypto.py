from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Dict, Tuple

from src.app.security.kms import decrypt_string, encrypt_string
from src.app.services.secrets_manager import get_secret
from src.app.models.db import db_session
from sqlalchemy import text


_PII_MARKER = "enc:v1:"
_PII_MARKER_V2 = "enc:v2:"


def _salt() -> str:
    return get_secret("PII_HASH_SALT", "shopsquire-default-salt") or "shopsquire-default-salt"


def _parse_keyring() -> Tuple[str | None, Dict[str, str]]:
    # Preferred format: PII_FERNET_KEYS="kid1:key1,kid2:key2"
    raw = str(get_secret("PII_FERNET_KEYS", "") or "")
    keyring: Dict[str, str] = {}
    if raw:
        for part in raw.split(","):
            if ":" not in part:
                continue
            kid, key = part.split(":", 1)
            kid = kid.strip()
            key = key.strip()
            if kid and key:
                keyring[kid] = key
    active = str(get_secret("PII_ACTIVE_KEY_ID", "") or "").strip() or None
    if not keyring:
        legacy = get_secret("PII_FERNET_KEY")
        if legacy:
            keyring["legacy"] = str(legacy)
            if not active:
                active = "legacy"
    if not active and keyring:
        active = next(iter(keyring.keys()))
    return active, keyring


def pii_hash(value: str | None) -> str | None:
    if not value:
        return None
    raw = f"{_salt()}::{value.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def encrypt_pii(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    v = str(value)
    if v.startswith(_PII_MARKER) or v.startswith(_PII_MARKER_V2) or v.startswith("kms:v1:"):
        return v
    # Prefer platform KMS wrapper; fallback to deterministic local key crypto.
    try:
        token = encrypt_string(v)
        if token and token != v:
            return _PII_MARKER + base64.b64encode(token.encode("utf-8")).decode("ascii")
    except Exception:
        pass
    active_kid, keyring = _parse_keyring()
    key = keyring.get(active_kid or "")
    if not key:
        return v
    try:
        from cryptography.fernet import Fernet  # type: ignore

        f = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
        enc = f.encrypt(v.encode("utf-8"))
        return f"{_PII_MARKER_V2}{active_kid}:{base64.b64encode(enc).decode('ascii')}"
    except Exception:
        return v


def decrypt_pii(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    v = str(value)
    payload = v
    kid_hint: str | None = None
    if v.startswith(_PII_MARKER_V2):
        try:
            rest = v[len(_PII_MARKER_V2):]
            kid_hint, b64_payload = rest.split(":", 1)
            payload = b64_payload
        except Exception:
            payload = v
    if v.startswith(_PII_MARKER):
        try:
            payload = base64.b64decode(v[len(_PII_MARKER) :]).decode("utf-8", errors="ignore")
        except Exception:
            payload = v
    elif v.startswith(_PII_MARKER_V2):
        # keep payload as base64 ciphertext for keyring decrypt path
        pass
    if payload.startswith("kms:v1:"):
        try:
            return decrypt_string(payload)
        except Exception:
            return value
    _, keyring = _parse_keyring()
    if not keyring:
        return value
    try:
        from cryptography.fernet import Fernet  # type: ignore

        key_candidates = []
        if kid_hint and kid_hint in keyring:
            key_candidates.append(keyring[kid_hint])
        key_candidates.extend([v for k, v in keyring.items() if not kid_hint or k != kid_hint])
        for key in key_candidates:
            try:
                f = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
                dec = f.decrypt(base64.b64decode(payload.encode("utf-8")))
                return dec.decode("utf-8", errors="ignore")
            except Exception:
                continue
        return value
    except Exception:
        return value


def rotate_pii_ciphertext(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    plain = decrypt_pii(value)
    if plain in (None, ""):
        return value
    return encrypt_pii(plain)


def rotate_encrypted_pii_columns(*, dry_run: bool = True, limit: int = 500) -> Dict[str, Any]:
    targets = [
        ("orders", "id", "guest_email_encrypted"),
        ("cases", "id", "guest_email_encrypted"),
        ("customers", "id", "email_encrypted"),
        ("customers", "id", "phone_encrypted"),
    ]
    out: Dict[str, Any] = {"dry_run": bool(dry_run), "limit": int(limit), "tables": [], "rotated": 0}
    per_target_limit = max(1, int(limit))
    for table, pk, enc_col in targets:
        rotated = 0
        scanned = 0
        try:
            with db_session() as db:
                rows = db.execute(
                    text(
                        f"""
                        SELECT {pk}, {enc_col}
                        FROM {table}
                        WHERE {enc_col} IS NOT NULL AND {enc_col} != ''
                        LIMIT :lim
                        """
                    ),
                    {"lim": per_target_limit},
                ).fetchall()
                for row in rows or []:
                    scanned += 1
                    rid = row[0]
                    current = row[1]
                    rotated_value = rotate_pii_ciphertext(current)
                    if rotated_value and rotated_value != current:
                        rotated += 1
                        if not dry_run:
                            db.execute(
                                text(f"UPDATE {table} SET {enc_col} = :v WHERE {pk} = :id"),
                                {"v": rotated_value, "id": rid},
                            )
                if not dry_run:
                    db.commit()
        except Exception as exc:
            out["tables"].append({"table": table, "column": enc_col, "scanned": scanned, "rotated": rotated, "error": str(exc)})
            continue
        out["tables"].append({"table": table, "column": enc_col, "scanned": scanned, "rotated": rotated})
        out["rotated"] += rotated
    return out


def encrypt_pii_fields(payload: Dict[str, Any], keys: list[str]) -> Dict[str, Any]:
    out = dict(payload or {})
    for k in keys:
        if k in out and isinstance(out.get(k), str):
            out[k] = encrypt_pii(out.get(k))
    return out


def decrypt_pii_fields(payload: Dict[str, Any], keys: list[str]) -> Dict[str, Any]:
    out = dict(payload or {})
    for k in keys:
        if k in out and isinstance(out.get(k), str):
            out[k] = decrypt_pii(out.get(k))
    return out


def maybe_encrypt_json_text(value: str | None) -> str | None:
    if not value:
        return value
    try:
        obj = json.loads(value)
    except Exception:
        return value
    if not isinstance(obj, dict):
        return value
    keys = ["email", "phone", "address", "guest_email", "customer_email"]
    enc = encrypt_pii_fields(obj, keys)
    try:
        return json.dumps(enc, ensure_ascii=False)
    except Exception:
        return value
