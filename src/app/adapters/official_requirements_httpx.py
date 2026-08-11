"""Provider-neutral HTTP adapter for enrolled official requirement sources.

The configured endpoint resolves a workload query against operator-enrolled
official documents and returns bounded ``claim_candidates``.  Transport and SSRF
controls are inherited from the generic research adapter; claim authority is
still assigned and validated by the provider registry and evidence clamps.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from src.app.adapters.external_research_httpx import HttpxResearchFetcher


class OfficialRequirementsHttpFetcher(HttpxResearchFetcher):
    def __init__(
        self,
        *,
        client: Optional[Any] = None,
        endpoint_template: Optional[str] = None,
        resolver: Optional[Callable[..., Any]] = None,
        allow_private: Optional[bool] = None,
        api_key: Optional[str] = None,
        auth_header: Optional[str] = None,
    ) -> None:
        credential = str(
            api_key if api_key is not None else os.getenv("OFFICIAL_REQUIREMENTS_API_KEY") or ""
        ).strip()
        header_name = str(
            auth_header
            if auth_header is not None
            else os.getenv("OFFICIAL_REQUIREMENTS_AUTH_HEADER") or "Authorization"
        ).strip()
        auth_scheme = str(os.getenv("OFFICIAL_REQUIREMENTS_AUTH_SCHEME") or "Bearer").strip()
        auth_value = f"{auth_scheme} {credential}".strip() if credential else ""
        super().__init__(
            client=client,
            search_url_template=(
                endpoint_template
                if endpoint_template is not None
                else os.getenv("OFFICIAL_REQUIREMENTS_API_URL") or ""
            ),
            resolver=resolver,
            allow_private=allow_private,
            user_agent="ShopSquire-Official-Requirements/1.0",
            request_headers={header_name: auth_value} if header_name and auth_value else None,
        )
