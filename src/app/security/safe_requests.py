from __future__ import annotations

import os
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

from src.app.security.url_guard import ensure_safe_outbound_url


_MAX_REDIRECTS = int(os.getenv("SAFE_REQUEST_MAX_REDIRECTS", "5") or 5)


def safe_request(
    method: str,
    url: str,
    *,
    timeout: float = 5.0,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Any = None,
    auth: Any = None,
    verify: Any = True,
    allow_redirects: bool = False,
    max_redirects: int = _MAX_REDIRECTS,
) -> requests.Response:
    """Perform an outbound HTTP request with mandatory SSRF URL validation.

    H01: Every redirect hop is validated against the SSRF guard to prevent
    DNS-rebinding or redirect-to-metadata attacks.
    """
    ensure_safe_outbound_url(str(url or ""))
    resp = requests.request(
        method=str(method or "GET").upper(),
        url=url,
        timeout=float(timeout),
        headers=headers,
        params=params,
        json=json_body,
        data=data,
        auth=auth,
        verify=verify,
        allow_redirects=False,  # always manual to validate each hop
    )
    if allow_redirects:
        for _ in range(max(0, max_redirects)):
            if resp.status_code not in (301, 302, 303, 307, 308):
                break
            location = (resp.headers.get("Location") or "").strip()
            if not location:
                break
            next_url = urljoin(url, location)
            ensure_safe_outbound_url(next_url)
            resp = requests.get(next_url, timeout=float(timeout), headers=headers, verify=verify, allow_redirects=False)
            url = next_url
    return resp


def safe_post(
    url: str,
    *,
    timeout: float = 5.0,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Any = None,
    auth: Any = None,
    verify: Any = True,
    allow_redirects: bool = False,
) -> requests.Response:
    return safe_request(
        "POST",
        url,
        timeout=timeout,
        headers=headers,
        json_body=json_body,
        data=data,
        auth=auth,
        verify=verify,
        allow_redirects=allow_redirects,
    )
