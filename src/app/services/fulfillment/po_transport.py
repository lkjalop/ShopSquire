"""Purchase-order provider adapter, using fake transport by default.

The HTTP adapter requires an idempotency key and a confirmed provider reference.
Missing receipts, transport exceptions and ambiguous responses return unknown;
provider rejection returns failed. Neither result proves that no effect occurred.
The workflow must reconcile before another dispatch. A provider's idempotency
implementation is external and has not been certified against a real ERP here.

These adapters do not authenticate people or grant commerce approval. Callers own
those boundaries; legacy PO distinct-person approval remains incomplete.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from contextlib import ExitStack
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class PoResult:
    po_ref: str
    status: str            # created | failed (known rejection) | unknown (reconcile)
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
        if not idempotency_key:
            return PoResult(po_ref='',status='failed',detail='idempotency_key_required')
        try:
            payload = {"supplier_ref": supplier_ref, "item_ref": item_ref, "quantity": quantity,
                       "unit_amount_cents": unit_amount_cents, "total_amount_cents": total_amount_cents,
                       "idempotency_key": idempotency_key}
            headers = {"X-Idempotency-Key": idempotency_key}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            with ExitStack() as owned:
                client = self._client
                if client is None:
                    import httpx
                    client = owned.enter_context(httpx.Client(timeout=10,follow_redirects=False))
                resp = client.post(self.url, json=payload, headers=headers)
                status=getattr(resp,'status_code',None)
                if status not in (200,201):
                    return PoResult(po_ref='',status='failed' if isinstance(status,int) and 400<=status<500 else 'unknown',
                        detail='provider_rejected' if isinstance(status,int) and 400<=status<500 else 'provider_outcome_unknown')
                data = resp.json() if hasattr(resp, "json") else {}
            data = data if isinstance(data, dict) else {}
            ref = data.get('po_ref') or data.get('id')
            if not isinstance(ref,str) or not ref.strip() or len(ref)>200:
                return PoResult(po_ref='',status='unknown',detail='provider_receipt_missing')
            return PoResult(po_ref=ref, status="created", detail="erp")
        except Exception:
            return PoResult(po_ref="", status="unknown", detail='transport_outcome_unknown')


def get_po_transport() -> PoTransport:
    """Select the PO transport from FULFILLMENT_PO_TRANSPORT (default 'sandbox')."""
    if str(os.getenv("FULFILLMENT_PO_TRANSPORT", "sandbox")).strip().lower() == "erp":
        return HttpErpTransport()
    return SandboxPoTransport()
