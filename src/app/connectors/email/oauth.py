from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import httpx
from src.app.services.secrets_manager import get_secret


_CACHE: dict[str, dict[str, Any]] = {}


def _cached(name: str) -> tuple[Optional[str], float]:
    c = _CACHE.get(name) or {}
    tok = c.get("token")
    exp = float(c.get("exp") or 0)
    return (str(tok) if tok else None), exp


def _set_cache(name: str, token: str, expires_in: int) -> str:
    exp = time.time() + max(10, int(expires_in or 0)) - 5
    _CACHE[name] = {"token": token, "exp": exp}
    return token


def get_gmail_access_token(client: httpx.Client | None = None) -> str:
    """Return a Gmail OAuth access token.

    Supports:
    - `GMAIL_ACCESS_TOKEN` (direct)
    - refresh flow using `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
    """
    tok = get_secret("GMAIL_ACCESS_TOKEN")
    if tok:
        return tok.strip()

    cached, exp = _cached("gmail")
    if cached and time.time() < exp:
        return cached

    cid = get_secret("GMAIL_CLIENT_ID")
    sec = get_secret("GMAIL_CLIENT_SECRET")
    rt = get_secret("GMAIL_REFRESH_TOKEN")
    if not (cid and sec and rt):
        raise RuntimeError("gmail_oauth_not_configured")

    http = client or httpx.Client(timeout=10)
    resp = http.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": cid,
            "client_secret": sec,
            "refresh_token": rt,
            "grant_type": "refresh_token",
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    data = resp.json()
    at = str(data.get("access_token") or "")
    if not at:
        raise RuntimeError("gmail_token_missing")
    return _set_cache("gmail", at, int(data.get("expires_in") or 3600))


def get_m365_access_token(client: httpx.Client | None = None) -> str:
    """Return a Microsoft Graph access token (client credentials)."""
    cached, exp = _cached("m365")
    if cached and time.time() < exp:
        return cached

    tenant = get_secret("M365_TENANT_ID")
    cid = get_secret("M365_CLIENT_ID")
    sec = get_secret("M365_CLIENT_SECRET")
    if not (tenant and cid and sec):
        tok = get_secret("M365_ACCESS_TOKEN")
        if tok:
            return tok.strip()
        raise RuntimeError("m365_oauth_not_configured")

    http = client or httpx.Client(timeout=10)
    resp = http.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": cid,
            "client_secret": sec,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    data = resp.json()
    at = str(data.get("access_token") or "")
    if not at:
        raise RuntimeError("m365_token_missing")
    return _set_cache("m365", at, int(data.get("expires_in") or 3600))
