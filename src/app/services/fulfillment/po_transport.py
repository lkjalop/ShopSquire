"""PO → ERP transport seam (agnostic CORE) — Phase-8 production transports.

purchase_order.execute creates a SANDBOX PO ref by default (records, transmits nothing). This is the
provider interface that lets a REAL ERP be wired at DEPLOY time without touching the workflow or the
gates — execute still fires the human-approved purchase_order_created transition; only the
system-of-record write differs.

  • SandboxPoTransport (default) — returns a PO- ref, creates nothing real (behaviour-identical).
  • HttpErpTransport (flag-gated, FULFILLMENT_PO_TRANSPORT=erp) — POSTs the PO to an ERP endpoint via an
    injected httpx-like client, idempotency-keyed so a retry can't double-create. status='failed' on any
    error — never raises into the workflow. UNEXERCISED vs a real ERP here; the build/post/failure path
    is tested with a fake client. Wire ERP_PO_URL / ERP_API_KEY at deploy to go live.

Vertical-blind (opaque refs · cents). The idempotency_key flows to the ERP so even a double-execute
maps to one PO.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class PoResult:
    po_ref: str
    status: str            # created | failed
    detail: str = ""       # transport label / error summary


class PoTransport(Protocol):
    def create(self, *, supplier_ref: str, item_ref: str, quantity: Any, unit_amount_cents: Any,
               total_amount_cents: Any, idempotency_key: str = "") -> PoResult: ...


class SandboxPoTransport:
    """The default — records a PO ref, transmits nothing to any real system."""

    def create(self, *, supplier_ref: str = "", item_ref: str = "", quantity: Any = None,
               unit_amount_cents: Any = None, total_amount_cents: Any = None,
               idempotency_key: str = "") -> PoResult:
        return PoResult(po_ref=f"PO-{uuid.uuid4().hex[:10].upper()}", status="created", detail="sandbox")


class HttpErpTransport:
    """Real ERP PO creation over HTTP (flag-gated). Deterministic + testable via an injected ``client``
    (default httpx.Client). Returns status='failed' on any error — it never raises into the workflow."""

    def __init__(self, *, url: Optional[str] = None, api_key: Optional[str] = None, client: Any = None):
        self.url = url or os.getenv("ERP_PO_URL", "")
        self.api_key = api_key if api_key is not None else os.getenv("ERP_API_KEY", "")
        self._client = client

    def create(self, *, supplier_ref: str = "", item_ref: str = "", quantity: Any = None,
               unit_amount_cents: Any = None, total_amount_cents: Any = None,
               idempotency_key: str = "") -> PoResult:
        if not self.url:
            return PoResult(po_ref="", status="failed", detail="no_erp_url")
        try:
            payload = {"supplier_ref": supplier_ref, "item_ref": item_ref, "quantity": quantity,
                       "unit_amount_cents": unit_amount_cents, "total_amount_cents": total_amount_cents,
                       "idempotency_key": idempotency_key}
            headers = {"X-Idempotency-Key": idempotency_key}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            client = self._client
            if client is None:
                import httpx
                client = httpx.Client(timeout=10)
            resp = client.post(self.url, json=payload, headers=headers)
            data = resp.json() if hasattr(resp, "json") else {}
            data = data if isinstance(data, dict) else {}
            ref = str(data.get("po_ref") or data.get("id") or f"ERP-{(idempotency_key or uuid.uuid4().hex)[:12].upper()}")
            return PoResult(po_ref=ref, status="created", detail="erp")
        except Exception as exc:
            return PoResult(po_ref="", status="failed", detail=str(exc)[:200])


def get_po_transport() -> PoTransport:
    """Select the PO transport from FULFILLMENT_PO_TRANSPORT (default 'sandbox')."""
    if str(os.getenv("FULFILLMENT_PO_TRANSPORT", "sandbox")).strip().lower() == "erp":
        return HttpErpTransport()
    return SandboxPoTransport()
