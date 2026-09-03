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


__all__ = ["OrderEconomics"]
