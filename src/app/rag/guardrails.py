from __future__ import annotations

import re
from typing import Optional

INJECTION_PATTERNS = [
    r"ignore\s+all",
    r"system\s+prompt",
    r"developer\s+override",
    r"###\s*instruction",
]


def allow_query(query: str) -> bool:
    text = (query or "").lower()
    return not any(re.search(pat, text) for pat in INJECTION_PATTERNS)


def allow_doc(tenant_id: Optional[str], doc_tenant_allowlist: Optional[list[str]]) -> bool:
    if not doc_tenant_allowlist:
        return True
    if not tenant_id:
        return False
    return tenant_id in doc_tenant_allowlist
