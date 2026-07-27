"""Compatibility boundary retained temporarily for callers while its name is migrated."""
from __future__ import annotations

from typing import Any, Dict

def delegate_legacy_recommendation(
    *, request: Any, params: Dict[str, Any], redis: Any, db: Any, role: str,
) -> Dict[str, Any]:
    """Serve the old delegation call through the V2-only compatibility boundary."""
    from src.app.services.recommendation_compatibility import serve_v2_compatibility

    normalized = dict(params or {})
    normalized["external_research_consent"] = (
        str(params.get("external_research_consent") or "").lower() == "true"
    )
    return serve_v2_compatibility(
        request=request,
        params=normalized,
        redis=redis,
        db=db,
        role=role,
    )
