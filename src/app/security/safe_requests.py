from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from src.app.security.url_guard import ensure_safe_outbound_url


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
) -> requests.Response:
    """Perform an outbound HTTP request with mandatory SSRF URL validation."""
    ensure_safe_outbound_url(str(url or ""))
    return requests.request(
        method=str(method or "GET").upper(),
        url=url,
        timeout=float(timeout),
        headers=headers,
        params=params,
        json=json_body,
        data=data,
        auth=auth,
        verify=verify,
        allow_redirects=allow_redirects,
    )


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
