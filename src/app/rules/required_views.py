from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class RequiredViewsResult:
    ok: bool
    required: List[str]
    present: List[str]
    missing: List[str]
    details: Dict[str, Any]


def _match_view(fname: str, keywords: List[str]) -> bool:
    f = (fname or "").lower()
    return any(k.lower() in f for k in (keywords or []))


def check_required_views(images: List[Tuple[str, bytes]], required_views_cfg: Dict[str, Any]) -> RequiredViewsResult:
    required = list(required_views_cfg.get("views") or [])
    kw = dict(required_views_cfg.get("keywords") or {})
    present: List[str] = []

    for view in required:
        keys = kw.get(view) or [view]
        if any(_match_view(fname, keys) for fname, _b in images):
            present.append(view)

    missing = [v for v in required if v not in present]
    min_images = int(required_views_cfg.get("min_images") or 0)
    ok = len(images) >= max(1, min_images) and (len(missing) == 0)

    # Required views are often advisory; the caller decides whether missing views
    # is a hard failure (strict mode).
    return RequiredViewsResult(
        ok=ok,
        required=required,
        present=present,
        missing=missing,
        details={"min_images": min_images},
    )

