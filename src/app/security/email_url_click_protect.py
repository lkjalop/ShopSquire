"""E-006 — Email URL rewriting / click-protect.

At delivery time, all http(s) links in the email HTML body are rewritten to
route through our signed click-guard endpoint::

    /api/v1/email-security/click?t=<HMAC-signed-token>

The guard endpoint (``verify_click_redirect``) then:

1. Validates the HMAC signature (prevents forged/tampered tokens).
2. Extracts the original URL.
3. Checks the URL against the IOC verdict cache (populated by the earlier
   detonation scan at ingest time).
4. Returns ``(original_url, blocked=False)`` to redirect, or
   ``(original_url, blocked=True)`` to show a block/warning page.

This closes the timing gap where a URL is clean at analysis time but is
later classified as malicious before the recipient clicks.

Usage::

    from src.app.security.email_url_click_protect import (
        rewrite_urls_in_email,
        verify_click_redirect,
    )

    # Outbound delivery path — rewrite body links
    email["body"] = rewrite_urls_in_email(
        email.get("body") or "",
        base_url="https://shopsquire.example.com",
        secret_key=settings.click_protect_secret,
        tenant_id=tenant_id,
    )

    # GET /api/v1/email-security/click?t=... handler
    url, blocked = verify_click_redirect(token, secret_key=settings.click_protect_secret)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import time
from typing import Any, Dict, Tuple
from urllib.parse import quote, urlencode, urlparse

logger = logging.getLogger("shopsquire.email_url_click_protect")

# In-process IOC verdict cache: url_sha256 → {"blocked": bool, "verdict": str, "exp": float}
_IOC_VERDICT_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = int(os.getenv("CLICK_PROTECT_CACHE_TTL", "900"))

# Regex matching http(s) URLs in HTML bodies.  We match href and src attributes
# plus bare links in plain text.
_URL_RE = re.compile(
    r'(?:href|src)=["\']?(https?://[^\s"\'<>]+)["\']?',
    re.IGNORECASE,
)
_PLAIN_URL_RE = re.compile(r'(?<!["\'])https?://[^\s<>"\']{8,}', re.IGNORECASE)

# Maximum token age accepted (15 minutes).  After this the link is re-verified.
_MAX_TOKEN_AGE_SEC = int(os.getenv("CLICK_PROTECT_TOKEN_TTL", "900"))


# ---------------------------------------------------------------------------
#  Token encoding / decoding helpers
# ---------------------------------------------------------------------------

def _encode_token(url: str, *, secret_key: str, tenant_id: str | None = None, ts: int | None = None) -> str:
    """Create a URL-safe HMAC-signed token encoding the target URL.

    Token layout (base64url, no padding)::

        <ts_hex>.<tenant_b64>.<url_b64>.<hmac_hex>

    HMAC-SHA256 is computed over ``"{ts}:{tenant}:{url}"``.
    """
    ts = ts if ts is not None else int(time.time())
    tenant = str(tenant_id or "")
    ts_hex = format(ts, "x")
    tenant_b64 = base64.urlsafe_b64encode(tenant.encode("utf-8")).decode("ascii").rstrip("=")
    url_b64 = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    msg = f"{ts_hex}:{tenant}:{url}".encode("utf-8")
    sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{ts_hex}.{tenant_b64}.{url_b64}.{sig}"


def _decode_token(
    token: str,
    *,
    secret_key: str,
    max_age_sec: int = _MAX_TOKEN_AGE_SEC,
) -> Tuple[str, str | None]:
    """Validate and decode a click-protect token.

    Returns ``(original_url, tenant_id_or_None)`` on success.
    Raises ``ValueError`` on invalid token, expired token, or failed HMAC.
    """
    try:
        parts = token.split(".", 3)
        if len(parts) != 4:
            raise ValueError("malformed token: expected 4 dot-separated parts")
        ts_hex, tenant_b64, url_b64, provided_sig = parts
        ts = int(ts_hex, 16)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"token parse error: {exc}") from exc

    age = time.time() - ts
    if age > max_age_sec:
        raise ValueError(f"token expired (age={int(age)}s, max={max_age_sec}s)")
    if age < -60:
        raise ValueError("token timestamp is in the future")

    # Decode fields
    def _pad(s: str) -> str:
        return s + "=" * ((4 - len(s) % 4) % 4)

    try:
        tenant = base64.urlsafe_b64decode(_pad(tenant_b64)).decode("utf-8")
        original_url = base64.urlsafe_b64decode(_pad(url_b64)).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"token field decode error: {exc}") from exc

    # Recompute HMAC and compare in constant time
    msg = f"{ts_hex}:{tenant}:{original_url}".encode("utf-8")
    expected_sig = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, provided_sig):
        raise ValueError("token HMAC verification failed")

    return original_url, tenant or None


# ---------------------------------------------------------------------------
#  IOC verdict cache (populated by sandbox/detonation, checked at click time)
# ---------------------------------------------------------------------------

def cache_ioc_verdict(url: str, *, blocked: bool, verdict: str = "review", ttl: int = _CACHE_TTL_SECONDS) -> None:
    """Store a sandbox/IOC verdict for a URL so click-guard can honour it."""
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    _IOC_VERDICT_CACHE[key] = {
        "blocked": bool(blocked),
        "verdict": str(verdict),
        "exp": time.time() + int(max(60, ttl)),
        "url": url[:200],
    }
    # Also attempt Redis for multi-worker consistency.
    try:
        from src.app.deps import get_redis  # type: ignore
        r = get_redis()
        if r.__class__.__name__ != "DummyRedis":
            import json as _json
            r.setex(
                f"click_protect:ioc:{key}",
                int(max(60, ttl)),
                _json.dumps({"blocked": bool(blocked), "verdict": verdict}),
            )
    except Exception:
        pass


def _lookup_ioc_verdict(url: str) -> Dict[str, Any] | None:
    """Check IOC verdict cache.  Returns cached entry or None if not found/expired."""
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    # Try Redis first
    try:
        from src.app.deps import get_redis  # type: ignore
        import json as _json
        r = get_redis()
        if r.__class__.__name__ != "DummyRedis":
            raw = r.get(f"click_protect:ioc:{key}")
            if raw:
                entry = _json.loads(raw)
                return {"blocked": bool(entry.get("blocked")), "verdict": str(entry.get("verdict") or "review")}
    except Exception:
        pass
    # Fall back to in-process cache
    item = _IOC_VERDICT_CACHE.get(key)
    if not item:
        return None
    if float(item.get("exp", 0)) < time.time():
        _IOC_VERDICT_CACHE.pop(key, None)
        return None
    return item


# ---------------------------------------------------------------------------
#  URL heuristic pre-check (fast path, no network call)
# ---------------------------------------------------------------------------

_SUSPICIOUS_TLDS = {".xyz", ".tk", ".top", ".click", ".link", ".cf", ".ml", ".ga", ".gq"}
_SHORT_LINK_HOSTS = {
    "bit.ly", "tinyurl.com", "t.co", "ow.ly", "goo.gl", "is.gd", "ift.tt",
    "buff.ly", "dlvr.it", "shorturl.at", "cutt.ly", "rebrand.ly",
}


def _heuristic_risk(url: str) -> float:
    """Return a 0..1 fast heuristic risk score for a URL.  No network calls."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
    except Exception:
        return 0.3

    risk = 0.0
    if any(host.endswith(tld) for tld in _SUSPICIOUS_TLDS):
        risk += 0.4
    if host in _SHORT_LINK_HOSTS:
        risk += 0.3
    if re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", host):
        risk += 0.5  # raw IP in URL — strong indicator
    if len(host.split(".")) > 5:
        risk += 0.2  # deeply nested subdomain
    if re.search(r"(?:invoice|payment|confirm|secure|update|verify|account|login)", path + query):
        risk += 0.2
    if "%" in path and sum(1 for c in path if c == "%") > 5:
        risk += 0.2  # heavy URL encoding
    return min(1.0, risk)


# ---------------------------------------------------------------------------
#  URL rewriting
# ---------------------------------------------------------------------------

def rewrite_urls_in_email(
    body: str,
    *,
    base_url: str,
    secret_key: str,
    tenant_id: str | None = None,
    rewrite_plain_text: bool = True,
) -> str:
    """Rewrite all http(s) links in an email HTML/text body through the click guard.

    Links already pointing at `base_url` (self-referencing guard links) are
    not double-wrapped.
    """
    if not body or not secret_key:
        return body

    guard_base = base_url.rstrip("/") + "/api/v1/email-security/click"

    def _wrap(url: str) -> str:
        if guard_base in url:
            return url  # already protected
        token = _encode_token(url, secret_key=secret_key, tenant_id=tenant_id)
        return f"{guard_base}?t={quote(token, safe='')}"

    def _replace_attr(m: re.Match) -> str:
        attr_prefix = m.group(0)[: m.start(1) - m.start(0)]
        url = m.group(1)
        wrapped = _wrap(url)
        # Preserve original attribute quoting style
        raw = m.group(0)
        if f'"{url}' in raw or f"{url}" in raw:
            return raw.replace(url, wrapped, 1)
        return raw.replace(url, wrapped, 1)

    rewritten = _URL_RE.sub(_replace_attr, body)
    if rewrite_plain_text:
        def _replace_plain(m: re.Match) -> str:
            url = m.group(0)
            if guard_base in url:
                return url
            return _wrap(url)
        rewritten = _PLAIN_URL_RE.sub(_replace_plain, rewritten)

    return rewritten


# ---------------------------------------------------------------------------
#  Click-time guard
# ---------------------------------------------------------------------------

def verify_click_redirect(
    token: str,
    *,
    secret_key: str,
    max_age_sec: int = _MAX_TOKEN_AGE_SEC,
) -> Tuple[str, bool]:
    """Validate a click-protect token and determine if the URL should be blocked.

    Returns ``(original_url, blocked)`` where ``blocked=True`` means the URL
    should NOT be followed (show a warning page instead).

    Never raises — always returns a result.  If the token is invalid this
    returns ``("", True)`` (block unknown/tampered links by default).
    """
    try:
        original_url, tenant_id = _decode_token(token, secret_key=secret_key, max_age_sec=max_age_sec)
    except ValueError as exc:
        logger.warning("click_protect: invalid token — %s", exc)
        return "", True

    # 1. IOC verdict cache (populated by earlier detonation scan)
    cached = _lookup_ioc_verdict(original_url)
    if cached is not None:
        blocked = bool(cached.get("blocked"))
        logger.info(
            "click_protect: url=%s verdict=%s blocked=%s (cached)",
            original_url[:80], cached.get("verdict"), blocked,
        )
        return original_url, blocked

    # 2. Fast heuristic pre-check (no network)
    risk = _heuristic_risk(original_url)
    if risk >= 0.7:
        logger.warning("click_protect: high-risk URL blocked by heuristic (score=%.2f) url=%s", risk, original_url[:80])
        # Cache the block verdict to avoid repeated heuristic evaluation
        cache_ioc_verdict(original_url, blocked=True, verdict="heuristic_block")
        return original_url, True

    # 3. URL not in cache and not blocked by heuristic → allow with logging
    logger.info("click_protect: url=%s allowed (heuristic_score=%.2f)", original_url[:80], risk)
    return original_url, False
