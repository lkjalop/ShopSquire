"""Fail-closed parsing for recommendation-router model output."""
from __future__ import annotations

import json
from typing import Any


def parse_router_payload(raw: str | None) -> dict[str, Any] | None:
    """Accept one JSON object; malformed/scalar/array output has no authority."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def parse_clarification_relation(raw: str | None) -> str:
    value = parse_router_payload(raw)
    relation = str((value or {}).get("clarification_relation") or "").strip().lower()
    return relation if relation in {"answer", "interrupt", "supersede", "ambiguous"} else "ambiguous"


__all__ = ["parse_clarification_relation", "parse_router_payload"]
