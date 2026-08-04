"""Price ↔ cents conversion helpers.

Single source of truth for the cents↔dollars boundary. Collapses 50+ inline
`price_cents / 100.0` / `int(round(price * 100))` sites that previously diverged
on rounding and `None` handling — the rounding-drift class that produced the
BAG `$0` / whole-vs-cents prose mismatch.

Semantics chosen to match the most common existing call sites so the helpers
are drop-in:
- `cents_to_dollars(c)`            → `float(c or 0) / 100.0`     (no rounding)
- `cents_to_dollars(c, ndigits=2)` → `round(float(c or 0) / 100.0, 2)`
- `dollars_to_cents(d)`            → `int(round(float(d or 0) * 100.0))`

Non-numeric / `None` inputs degrade to `0` / `0.0` (mirrors the `or 0` idiom
the call sites already used).
"""

from __future__ import annotations

from typing import Any

__all__ = ["cents_to_dollars", "dollars_to_cents"]


def cents_to_dollars(cents: Any, *, ndigits: int | None = None) -> float:
    """Return `cents` as dollars (float). `None`/non-numeric → ``0.0``.

    `ndigits` rounds to that decimal place; omit for the raw float (matches
    the existing `price_cents / 100.0` idiom).
    """
    try:
        value = float(cents or 0) / 100.0
    except (TypeError, ValueError):
        return 0.0
    return round(value, ndigits) if ndigits is not None else value


def dollars_to_cents(dollars: Any) -> int:
    """Return `dollars` as integer cents, rounded. `None`/non-numeric → ``0``."""
    try:
        return int(round(float(dollars or 0) * 100.0))
    except (TypeError, ValueError):
        return 0
