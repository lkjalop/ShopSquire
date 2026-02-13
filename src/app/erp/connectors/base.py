from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol


@dataclass(frozen=True)
class InventoryRecord:
    sku: str
    warehouse: str
    stock: int
    updated_at: str | None = None
    source: str | None = None


class InventoryConnector(Protocol):
    """Read-only connector interface for inventory sources (ERP/WMS/IM).

    Phase 5 goal: multiple connectors populate a canonical inventory model.
    This interface keeps the first step simple: snapshots are pulled and
    normalized, then written into ShopSquire's DB by a sync engine.
    """

    def name(self) -> str: ...

    def fetch_inventory(self, *, tenant_id: str | None = None) -> List[InventoryRecord]: ...

    def health(self) -> Dict[str, Any]: ...

