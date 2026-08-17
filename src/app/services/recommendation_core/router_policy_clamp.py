"""Closed-vocabulary policy clamps for recommendation routing."""
from __future__ import annotations

from src.app.services.recommendation_core.envelope import LANES


_LANE_ALIASES = {
    "BULK": "PROCUREMENT",
    "BULK_QUOTE": "PROCUREMENT",
    "QUOTE": "PROCUREMENT",
    "RFQ": "PROCUREMENT",
}


def clamp_lane(value: object) -> str | None:
    lane = str(value or "").strip().upper()
    lane = _LANE_ALIASES.get(lane, lane)
    return lane if lane in LANES else None


__all__ = ["clamp_lane"]
