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


def bounded_quantity_proposal(data, raw_requirements, allowed_ops):
    """Read the existing numeric proposal shapes; buyer grounding is separate."""
    import math as _math
    quantity = None
    _qv = data.get("quantity")
    if (isinstance(_qv, (int, float)) and not isinstance(_qv, bool) and _math.isfinite(_qv)
            and float(_qv).is_integer() and 1 <= int(_qv) <= 100_000):   # finite + integral (P0.7)
        quantity = int(_qv)
    if quantity is None:
        # graceful + model-agnostic: honor a count the model put in `requirements` (a common habit).
        # Validate the OPERATOR (P0.7) — not a regex on the query, just reading the model flexibly.
        _cnt = raw_requirements.get("count")
        if (isinstance(_cnt, (list, tuple)) and len(_cnt) == 2 and str(_cnt[0]) in allowed_ops
                and isinstance(_cnt[1], (int, float)) and not isinstance(_cnt[1], bool)
                and _math.isfinite(_cnt[1]) and 1 <= int(_cnt[1]) <= 100_000):
            quantity = int(_cnt[1])
    return quantity
