"""Inventory availability notices for requested brands."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def emit_inventory_brand_notice(
    *,
    results: list[dict],
    constraints: dict,
    decision_id: str | None,
    trace_id: str | None,
    trace_fn: Callable[..., Any] | None = None,
) -> tuple[str | None, list[str]]:
    """Return missing requested brands and emit best-effort trace evidence."""
    try:
        requested = {
            str(brand).strip().lower()
            for brand in constraints.get("brands") or []
            if brand is not None and str(brand).strip()
        }
        excluded = {
            str(brand).strip().lower()
            for brand in constraints.get("brand_excludes") or []
            if brand is not None and str(brand).strip()
        }
        requested -= excluded
        if not requested:
            return None, []
        matched = set()
        for result in results or []:
            name = str(result.get("name") or "").lower()
            guessed_brand = name.split(" ")[0] if name else ""
            if guessed_brand and guessed_brand in requested:
                matched.add(guessed_brand)
        unmatched = sorted(requested - matched)
        if not unmatched:
            return None, []
        if trace_fn is not None:
            for event_type, payload in (
                (
                    "inventory_notice",
                    {
                        "unmatched_brands": unmatched,
                        "requested": sorted(requested),
                    },
                ),
                (
                    "supplier_missing",
                    {
                        "missing_suppliers_for": unmatched,
                        "requested": sorted(requested),
                    },
                ),
            ):
                try:
                    trace_fn(
                        trace_id=decision_id or trace_id,
                        event_type=event_type,
                        source_type="agent",
                        source_id="Inventory_Agent",
                        target_type="system",
                        target_id=None,
                        payload=payload,
                    )
                except Exception:
                    continue
        note = (
            " Note: We currently don’t have active suppliers for "
            f"{', '.join(unmatched)} in this range. Showing closest "
            "alternatives and monitoring restock."
        )
        return note, unmatched
    except Exception:
        return None, []
