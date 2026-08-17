"""Inventory source adapter (agnostic CORE) — the ONE seam that decides where stock truth comes from.

Production posture: the canonical `commerce_catalog.inventory_level` is the system-of-record once it's
populated (a real ecommerce/supplier sync via the platform adapters). The legacy
`inventory_query_service.batch_stock_levels` stays the fallback so nothing regresses before the catalog
is seeded.

The merge is PER-SKU on purpose: when `COMMERCE_CATALOG_ENABLED` is on we overlay the canonical
`available` only for the skus the catalog actually HAS — a sku the catalog doesn't know keeps its legacy
value (a half-synced catalog never zeroes out real stock). Flag-off → pure legacy (default unchanged).

Vertical-blind (sku → count); both sources own their own DB session; injectable for tests; never raises.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from src.app.services.operational_tool_scope import operational_read_receipt
from src.app.services.tool_capability_selector import ToolCapability


def _legacy_levels(skus: List[str]) -> Dict[str, int]:
    from src.app.services.inventory_query_service import batch_stock_levels
    return batch_stock_levels(skus) or {}


def _canonical_levels(skus: List[str], tenant_id: str) -> Dict[str, int]:
    """Canonical `available` per sku, for the skus the catalog has (own DB session). {} on any failure."""
    try:
        from src.app.models.db import db_session
        from src.app.services import commerce_catalog
        with db_session() as db:
            return commerce_catalog.batch_available(db, skus, tenant_id=tenant_id) or {}
    except Exception:
        return {}


def _overlay(legacy: Dict[str, int], canonical: Dict[str, int]) -> Dict[str, int]:
    """Canonical wins for the skus it has; legacy fills the rest. Pure (testable)."""
    merged = dict(legacy or {})
    for sku, avail in (canonical or {}).items():
        if avail is not None:
            merged[str(sku)] = int(avail)
    return merged


def stock_levels(
    skus: List[str],
    *,
    tenant_id: str = "default",
    legacy_fn: Optional[Callable[[List[str]], Dict[str, int]]] = None,
    canonical_fn: Optional[Callable[[List[str], str], Dict[str, int]]] = None,
) -> Dict[str, int]:
    """{sku: stock_count}. Legacy baseline, with the canonical catalog overlaid per-sku when
    COMMERCE_CATALOG_ENABLED is set. Deps injectable for tests; never raises."""
    skus = [str(s) for s in (skus or []) if str(s).strip()]
    if not skus:
        return {}
    legacy = (legacy_fn or _legacy_levels)(skus) or {}
    from src.app.services import commerce_catalog
    if not commerce_catalog.catalog_enabled():
        return legacy  # flag off → legacy only (default behaviour unchanged)
    canonical = (canonical_fn or _canonical_levels)(skus, tenant_id) or {}
    return _overlay(legacy, canonical)


def stock_levels_with_receipt(
    skus: List[str], *, tenant_id: str = "default",
    legacy_fn: Optional[Callable[[List[str]], Dict[str, int]]] = None,
    canonical_fn: Optional[Callable[[List[str], str], Dict[str, int]]] = None,
) -> Dict[str, object]:
    """Return inventory values and the deterministic source-selection receipt."""
    from src.app.services import commerce_catalog

    canonical_enabled = commerce_catalog.catalog_enabled()
    levels = stock_levels(
        skus, tenant_id=tenant_id, legacy_fn=legacy_fn, canonical_fn=canonical_fn,
    )
    receipt = operational_read_receipt(
        capability=ToolCapability.INVENTORY_AVAILABILITY,
        tenant_id=tenant_id,
        deployment_id=(
            "commerce_catalog.inventory_level" if canonical_enabled
            else "legacy_inventory_query"
        ),
        enabled=True, freshness_state="unknown", health_status="healthy",
        authority_score=90 if canonical_enabled else 55,
    )
    return {
        "levels": levels,
        "tool_selection_receipt": receipt.model_dump(mode="json"),
    }
