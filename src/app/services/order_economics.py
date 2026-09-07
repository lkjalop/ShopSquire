"""Canonical order-level economics shared by chat, panels and Decision Trace."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class OrderEconomics:
    quantity: int
    quantity_unit: str
    budget_scope: str
    total_budget_cents: Optional[int]
    per_unit_cap_cents: Optional[int]
    qualified_unit_floor_cents: int
    required_total_cents: int
    max_affordable_quantity: Optional[int]
    budget_shortfall_cents: Optional[int]
    verdict: str
    tradeoffs: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    local_stock: Optional[int] = None
    network_transferable: Optional[int] = None
    supplier_shortfall: Optional[int] = None

    @classmethod
    def from_assessment(
        cls,
        value: Mapping[str, Any],
        *,
        budget_scope: str,
        quantity_unit: str = "unit",
    ) -> "OrderEconomics":
        quantity = int(value["quantity"])
        total = value.get("total_cents")
        required = int(value["needed_cents"])
        total_int = int(total) if total is not None else None
        return cls(
            quantity=quantity,
            quantity_unit=quantity_unit,
            budget_scope=str(budget_scope or "unknown"),
            total_budget_cents=total_int,
            per_unit_cap_cents=(int(value["per_unit_cents"]) if value.get("per_unit_cents") is not None else None),
            qualified_unit_floor_cents=int(value["floor_cents"]),
            required_total_cents=required,
            max_affordable_quantity=(int(value["units_affordable"]) if value.get("units_affordable") is not None else None),
            budget_shortfall_cents=(max(0, required - total_int) if total_int is not None else None),
            verdict=str(value.get("verdict") or "unsized"),
            tradeoffs=tuple(dict(item) for item in value.get("tradeoffs") or () if isinstance(item, Mapping)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tradeoffs"] = [dict(item) for item in self.tradeoffs]
        return payload


def project_stock_economics(economics: Mapping[str, Any], availability: Mapping[str, Any] | None) -> dict[str, Any]:
    """Join a read-only stock receipt without turning financial fit into stock proof."""
    result = dict(economics)
    if not availability or availability.get("applicable") is False:
        return result
    if availability.get("requested_qty", result.get("quantity")) != result.get("quantity"):
        return result
    snapshot = availability.get("inventory_snapshot")
    if (isinstance(snapshot, Mapping) and snapshot.get("conservation_ok") is True
            and snapshot.get("requested_quantity") == result.get("quantity")):
        counts = [snapshot.get(key) for key in ("local_atp", "transferable", "unconfirmed_shortfall")]
        if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in counts):
            result.update(stock_sku=availability.get("sku"), local_stock=counts[0],
                network_transferable=counts[1], supplier_shortfall=counts[2],
                stock_shortfall=max(0, int(result["quantity"]) - counts[0] - counts[1]),
                stock_evidence_status=snapshot.get("status", "unknown"),
                stock_freshness_status=snapshot.get("freshness_status", "unknown"),
                stock_observed_at=snapshot.get("observed_at"))
            return result
    stock = availability.get("in_stock")
    if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
        return result
    quantity = int(result["quantity"])
    transferable = availability.get("network_transferable")
    known_transfer = isinstance(transferable, int) and not isinstance(transferable, bool) and transferable >= 0
    result.update(
        stock_sku=availability.get("sku"), local_stock=stock,
        stock_shortfall=max(0, quantity - stock),
        network_transferable=transferable if known_transfer else None,
        supplier_shortfall=max(0, quantity - stock - transferable) if known_transfer else None,
        stock_evidence_status="observed",
    )
    return result


__all__ = ["OrderEconomics", "project_stock_economics"]
