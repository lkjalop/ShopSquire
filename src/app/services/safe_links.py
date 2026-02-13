from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.email_enrichment import detonate_targets, enrich_iocs


def _secret() -> str:
    return str(os.getenv("SAFE_LINK_SECRET", "dev-safe-link-secret"))


def _base() -> str:
    return str(os.getenv("SAFE_LINK_BASE_URL", "http://127.0.0.1:8080")).rstrip("/")


def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS safe_link_tokens (
                        token TEXT PRIMARY KEY,
                        tenant_id TEXT,
                        original_url TEXT NOT NULL,
                        campaign_id TEXT,
                        created_at INTEGER NOT NULL,
                        expires_at INTEGER NOT NULL,
                        click_count INTEGER NOT NULL DEFAULT 0,
                        last_clicked_at INTEGER,
                        last_verdict TEXT,
                        last_reasons_json TEXT
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _sign(payload: str) -> str:
    return hmac.new(_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _encode_token(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_token(tok: str) -> str:
    pad = "=" * ((4 - len(tok) % 4) % 4)
    return base64.urlsafe_b64decode((tok + pad).encode("ascii")).decode("utf-8", errors="ignore")


def create_safe_link(*, tenant_id: str | None, original_url: str, campaign_id: str | None = None, ttl_seconds: int = 7 * 24 * 3600) -> Dict[str, Any]:
    _ensure_table()
    now = int(time.time())
    exp = int(now + max(60, int(ttl_seconds or 0)))
    lid = f"sl-{uuid.uuid4().hex[:18]}"
    payload = f"{lid}:{exp}"
    token = _encode_token(f"{payload}:{_sign(payload)}")
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO safe_link_tokens
                (token, tenant_id, original_url, campaign_id, created_at, expires_at, click_count)
                VALUES
                (:token, :tenant_id, :original_url, :campaign_id, :created_at, :expires_at, 0)
                """
            ),
            {
                "token": token,
                "tenant_id": tenant_id,
                "original_url": original_url,
                "campaign_id": campaign_id,
                "created_at": now,
                "expires_at": exp,
            },
        )
        db.commit()
    return {"token": token, "safe_url": f"{_base()}/api/v1/safe-links/r/{token}", "expires_at": exp}


def _resolve_row(token: str) -> Dict[str, Any] | None:
    _ensure_table()
    try:
        with db_session() as db:
            r = db.execute(
                text(
                    """
                    SELECT token, tenant_id, original_url, campaign_id, created_at, expires_at, click_count, last_verdict, last_reasons_json
                    FROM safe_link_tokens
                    WHERE token = :token
                    LIMIT 1
                    """
                ),
                {"token": token},
            ).fetchone()
        if not r:
            return None
        return {
            "token": r[0],
            "tenant_id": r[1],
            "original_url": r[2],
            "campaign_id": r[3],
            "created_at": int(r[4] or 0),
            "expires_at": int(r[5] or 0),
            "click_count": int(r[6] or 0),
            "last_verdict": r[7],
            "last_reasons": json.loads(r[8]) if r[8] else [],
        }
    except Exception:
        return None


def _verify_token(token: str) -> bool:
    try:
        decoded = _decode_token(token)
        parts = decoded.split(":")
        if len(parts) < 3:
            return False
        lid = parts[0]
        exp = parts[1]
        sig = parts[2]
        payload = f"{lid}:{exp}"
        return hmac.compare_digest(sig, _sign(payload))
    except Exception:
        return False


def recheck_safe_link(*, token: str, ip: str | None = None, user_agent: str | None = None) -> Dict[str, Any]:
    if not _verify_token(token):
        return {"status": "invalid", "verdict": "block", "reasons": ["token_invalid"]}
    row = _resolve_row(token)
    if not row:
        return {"status": "not_found", "verdict": "block", "reasons": ["token_not_found"]}
    now = int(time.time())
    if now > int(row.get("expires_at") or 0):
        return {"status": "expired", "verdict": "block", "reasons": ["token_expired"], "url": row.get("original_url")}
    url = str(row.get("original_url") or "")
    tenant_id = str(row.get("tenant_id") or "") or None
    reasons: List[str] = []
    verdict = "allow"
    try:
        enr = enrich_iocs([{"type": "url", "value": url}], tenant_id=tenant_id)
    except Exception:
        enr = {"malicious_hits": 0}
        reasons.append("enrichment_unavailable")
    try:
        det = detonate_targets([url], [])
    except Exception:
        det = {"malicious": False}
        reasons.append("detonation_unavailable")
    if int((enr or {}).get("malicious_hits") or 0) > 0:
        verdict = "block"
        reasons.append("ioc_enrichment_malicious_hit")
    if bool((det or {}).get("malicious")):
        verdict = "block"
        reasons.append("sandbox_detonation_malicious")
    with db_session() as db:
        db.execute(
            text(
                """
                UPDATE safe_link_tokens
                SET click_count = click_count + 1,
                    last_clicked_at = :now,
                    last_verdict = :verdict,
                    last_reasons_json = :reasons
                WHERE token = :token
                """
            ),
            {"token": token, "now": now, "verdict": verdict, "reasons": json.dumps(reasons, ensure_ascii=False)},
        )
        db.commit()
    return {
        "status": "ok",
        "verdict": verdict,
        "reasons": reasons,
        "url": url,
        "tenant_id": tenant_id,
        "ip": ip,
        "user_agent_hash": (hashlib.sha256((user_agent or "").encode("utf-8")).hexdigest()[:16] if user_agent else None),
    }

