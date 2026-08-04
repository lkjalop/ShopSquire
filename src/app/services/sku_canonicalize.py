"""Collapse duplicate listings of the SAME physical product to one canonical card.

The seeded catalog carries the same product under more than one SKU (e.g. the MSI
Thin A15 as both LP021 and LAP-0020; the Dell DC15255 twice), so a single result
set shows the same laptop two or three times. This is a GENERIC commerce concern
(one product, many SKUs) — it lives in core and is vertical-agnostic: identity is
the normalised product name, and when two rows collapse we keep the most useful
record (richest specs, then higher score, then in stock, then cheaper).

It does NOT merge genuinely different configurations: the product names embed the
distinguishing specs (size, refresh, CPU, GPU), so different configs normalise to
different identities and are preserved.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_WS = re.compile(r"\s+")


def canonical_identity(row: Dict[str, Any] | None) -> str:
    """Vertical-agnostic identity for a listing: normalised product name."""
    name = str((row or {}).get("name") or "").strip().lower()
    name = _WS.sub(" ", name)
    return name


def _spec_completeness(row: Dict[str, Any]) -> int:
    specs = row.get("specs")
    if not isinstance(specs, dict):
        return 0
    return sum(1 for v in specs.values() if v not in (None, "", "?", [], {}))


def _is_better(candidate: Dict[str, Any], incumbent: Dict[str, Any]) -> bool:
    """True if `candidate` is the better record to keep for a duplicate identity."""
    c_specs, i_specs = _spec_completeness(candidate), _spec_completeness(incumbent)
    if c_specs != i_specs:
        return c_specs > i_specs
    c_score = float(candidate.get("score") or candidate.get("score_norm") or 0.0)
    i_score = float(incumbent.get("score") or incumbent.get("score_norm") or 0.0)
    if c_score != i_score:
        return c_score > i_score
    c_stock = int(candidate.get("stock") or 0) > 0
    i_stock = int(incumbent.get("stock") or 0) > 0
    if c_stock != i_stock:
        return c_stock
    c_price = int(candidate.get("price_cents") or 0) or 10**12
    i_price = int(incumbent.get("price_cents") or 0) or 10**12
    return c_price < i_price


def canonicalize(
    rows: List[Dict[str, Any]] | None,
    *,
    identity_fn=canonical_identity,
) -> List[Dict[str, Any]]:
    """Return `rows` with duplicate products collapsed, preserving first-seen order
    and keeping the best record per identity. Rows without a usable identity (no
    name) are passed through untouched."""
    if not rows:
        return list(rows or [])
    pos: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        key = identity_fn(row)
        if not key:
            out.append(row)
            continue
        if key in pos:
            idx = pos[key]
            if _is_better(row, out[idx]):
                out[idx] = row
            continue
        pos[key] = len(out)
        out.append(row)
    return out


def duplicate_skus(rows: List[Dict[str, Any]] | None) -> Dict[str, List[Optional[str]]]:
    """Diagnostic: identity -> [skus...] for identities that appear more than once."""
    groups: Dict[str, List[Optional[str]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = canonical_identity(row)
        if key:
            groups.setdefault(key, []).append(row.get("sku"))
    return {k: v for k, v in groups.items() if len(v) > 1}
