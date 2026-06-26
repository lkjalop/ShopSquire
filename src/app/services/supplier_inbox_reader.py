"""Supplier inbox reader (agnostic CORE) — bounded, READ-ONLY supplier-history context for a draft.

Summarizes recent dealings with a supplier (last invoiced amount, how often/when we've heard from them,
the verified contact email) so the Procurement_Agent can draft in-context instead of cold. It is STRICTLY
read-only and tightly bounded:
  • never writes, never sends, never escalates;
  • NEVER picks the recipient — the trusted-domain allowlist stays the only recipient source. The history
    is keyed on a domain that was ALREADY resolved from the allowlist, so a poisoned inbox can't redirect
    a message.
MAESTRO: Supplier_Inbox_Reader (can_write_db=False, can_call_external_api=False, max_autonomous_value=0).

Sources are injectable (testable); the defaults read existing tables best-effort, tenant-scoped:
  • supplier_baseline_events — historical per-(tenant, sha256(domain)[:16]) invoice amounts + timestamps;
  • kyv_vendors.contact_email — the verified vendor contact.
Vertical-blind (domain · cents · email); never raises.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

DEFAULT_TENANT = "default"


@dataclass(frozen=True)
class SupplierContext:
    domain: str
    observations: int                       # prior messages on file for this supplier
    last_invoice_cents: Optional[int]        # most recent invoiced amount (a "last quote" proxy)
    last_seen_at: Optional[str]
    contact_email: Optional[str]

    def known(self) -> bool:
        return self.observations > 0 or self.last_invoice_cents is not None or bool(self.contact_email)

    def summary(self) -> str:
        bits: List[str] = []
        if self.last_invoice_cents is not None:
            bits.append(f"last invoice ~{self.last_invoice_cents / 100:.0f}")
        if self.observations:
            bits.append(f"{self.observations} prior message(s)")
        if self.last_seen_at:
            bits.append(f"last seen {str(self.last_seen_at)[:10]}")
        if self.contact_email:
            bits.append(f"contact {self.contact_email}")
        return "; ".join(bits) or "no prior history"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["summary"] = self.summary()
        return d


def _hash16(domain: str) -> str:
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()[:16]


def _default_history(domain: str, window_days: int, tenant_id: str) -> List[Dict[str, Any]]:
    """Recent (tenant, domain) baseline events — invoice amount + timestamp. [] on any failure."""
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session
        with db_session() as db:
            rows = db.execute(text(
                "SELECT event_ts, invoice_amount FROM supplier_baseline_events "
                "WHERE tenant_id=:t AND sender_domain_hash=:sdh ORDER BY event_ts ASC LIMIT 500"),
                {"t": tenant_id, "sdh": _hash16(domain)}).fetchall()
        return [{"event_ts": r[0], "invoice_amount": r[1]} for r in rows]
    except Exception:
        return []


def _default_contact(domain: str, tenant_id: str) -> Optional[str]:
    """The verified vendor contact email for a domain. None on any failure."""
    try:
        from src.app.security.kyv_registry import lookup_vendor_by_domain
        v = lookup_vendor_by_domain(tenant_id=tenant_id, domain=domain) or {}
        return v.get("contact_email")
    except Exception:
        return None


def _safe_list(fn: Callable, *args) -> List[Dict[str, Any]]:
    try:
        return list(fn(*args) or [])
    except Exception:
        return []


def _safe_one(fn: Callable, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def recent_supplier_context(
    *,
    domain: str,
    window_days: int = 90,
    tenant_id: str = DEFAULT_TENANT,
    history_fn: Optional[Callable[[str, int, str], List[Dict[str, Any]]]] = None,
    contact_fn: Optional[Callable[[str, str], Optional[str]]] = None,
) -> Optional[SupplierContext]:
    """Read-only context for an ALREADY-resolved supplier domain. Returns None when nothing is known
    (so a caller adds no evidence rather than an empty one). Never raises."""
    domain = str(domain or "").strip().lower()
    if not domain:
        return None
    history = _safe_list(history_fn or _default_history, domain, int(window_days), tenant_id)
    contact = _safe_one(contact_fn or _default_contact, domain, tenant_id)

    amounts = [h.get("invoice_amount") for h in history if h.get("invoice_amount") is not None]
    last_invoice_cents: Optional[int] = None
    if amounts:
        try:
            last_invoice_cents = int(round(float(amounts[-1]) * 100))  # baseline amounts are dollars
        except Exception:
            last_invoice_cents = None
    last_seen = history[-1].get("event_ts") if history else None

    ctx = SupplierContext(
        domain=domain, observations=len(history), last_invoice_cents=last_invoice_cents,
        last_seen_at=last_seen, contact_email=(str(contact) if contact else None),
    )
    return ctx if ctx.known() else None
