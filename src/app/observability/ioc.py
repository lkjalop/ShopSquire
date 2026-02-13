from __future__ import annotations

from typing import Any, Dict, List
import re


def add_ioc_tags(event: Dict[str, Any]) -> List[str]:
    """Derive minimal IoC/supply-chain tags from an event payload.

    Examples:
      - Typosquat-like package names
      - Unverified external URLs
      - Suspicious version patterns (pre-release in prod)
    """
    tags: List[str] = []
    try:
        pkg = str(event.get("package") or event.get("dependency") or "")
        ver = str(event.get("version") or "")
        url = str(event.get("source_url") or event.get("url") or "")
        # typosquat heuristics for popular ecosystems
        suspicious_patterns = [
            r"^reqe?usts$",  # requests typosquat
            r"^tens?orflow$",
            r"^numpyy$",
        ]
        for pat in suspicious_patterns:
            if pkg and re.match(pat, pkg, flags=re.IGNORECASE):
                tags.append("ioc:typosquat")
                break
        # pre-release in high-criticality context
        if ver and re.search(r"(alpha|beta|rc)\d*", ver, flags=re.IGNORECASE):
            tags.append("ioc:prerelease")
        # external unverified sources
        if url and re.search(r"^https?://", url) and not re.search(r"github\.com|pypi\.org|npmjs\.com", url):
            tags.append("ioc:external_source")
    except Exception:
        pass
    return tags
