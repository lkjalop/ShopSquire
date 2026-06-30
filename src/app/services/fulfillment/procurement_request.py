"""Procurement Request (PR) identity (agnostic CORE) — the stable anchor for an order across mind-changes.

A buyer amends an order repeatedly. The order must keep ONE identity across every amendment (so cases/drafts
don't churn or duplicate), minted once when sourcing intent crystallises and rotated only on a lifecycle event
(order placed, cart cleared, or idle). The per-turn trace id rotated every turn (→ duplicate cases); the bare
session id never rotated (→ a new order collided with a still-open prior order). This module is the correct
grain: a PR id bound to the buyer + cart-open moment, plus a naming hierarchy and a rotation policy.

The naming hierarchy (audit anchor → leaves), each child append-only under its parent:
    PR    PR-{tenant}-{YYYYMMDD}-{short}     ← the anchor + single source of truth (== order_id)
     CASE CASE-{PR}-{group}                  ← one per supplier group, re-materialised per amendment
     PO   PO-{PR}-{seq}                      ← minted at cart-confirm (Gate 1)
     GR   GR-{PO}   /   INV INV-{PO}          ← goods receipt / invoice (3-way match)

Vertical-blind: PRs/POs are opaque ids; everything here is ids, counts, dates, and a boolean policy. Pure;
never raises. The retention boundary (ephemeral pre-confirm, durable bitemporal post-confirm) is documented in
docs/SHOPSQUIRE_PROCUREMENT_REQUEST_IDENTITY_AND_IRREVERSIBILITY_2026-06-30.md.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional

# Durable retention window for a materialised PR's bitemporal version chain (financial/procurement records).
RETENTION_WINDOW_DAYS = 365 * 7
# A cart left idle longer than this must NOT capture an unrelated future order — the safety-net rotation.
DEFAULT_IDLE_TTL_SECONDS = 24 * 3600

_PR_RE = re.compile(r"^PR-(?P<tenant>[a-z0-9_-]+)-(?P<date>\d{8})-(?P<short>[0-9a-f]{8,})$", re.IGNORECASE)
_SAFE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _slug(s: Any, *, default: str = "x") -> str:
    out = _SAFE.sub("-", str(s or "").strip().lower()).strip("-")
    return out or default


def _yyyymmdd(opened_at_iso: str) -> str:
    """The date portion of an ISO timestamp (space- or T-separated), digits only. '' → 'unknown' shape avoided
    by the caller always passing a real open time."""
    s = str(opened_at_iso or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return (m.group(1) + m.group(2) + m.group(3)) if m else "00000000"


def mint_pr_id(*, tenant_id: str, buyer_key: str, opened_at_iso: str, nonce: str = "") -> str:
    """Mint a Procurement Request id, ONCE per cart-open. Deterministic on its inputs (so an idempotent re-mint
    with the same buyer + open-moment + nonce yields the same id), while ``nonce`` (a per-cart token the caller
    supplies) keeps two carts the same buyer opens at the same second distinct."""
    tenant = _slug(tenant_id, default="default")
    digest = hashlib.sha256(f"{tenant}|{buyer_key}|{opened_at_iso}|{nonce}".encode("utf-8")).hexdigest()[:10]
    return f"PR-{tenant}-{_yyyymmdd(opened_at_iso)}-{digest}"


def is_pr_id(value: Any) -> bool:
    return bool(_PR_RE.match(str(value or "")))


def parse_pr_id(pr_id: str) -> Dict[str, str]:
    """Decompose a PR id for audit — {tenant, date, short}. Empty dict if not a PR id."""
    m = _PR_RE.match(str(pr_id or ""))
    return {"tenant": m.group("tenant"), "date": m.group("date"), "short": m.group("short")} if m else {}


def case_ref(pr_id: str, supplier_group: str) -> str:
    """Stable id for one supplier-group case under a PR — CASE-{PR}-{group}."""
    return f"CASE-{str(pr_id or '').strip()}-{_slug(supplier_group)}"


def po_ref(pr_id: str, seq: int = 1) -> str:
    """The PO minted for a PR at cart-confirm — PO-{PR}-{seq}."""
    return f"PO-{str(pr_id or '').strip()}-{max(1, int(seq or 1))}"


def goods_receipt_ref(po: str) -> str:
    return f"GR-{str(po or '').strip()}"


def invoice_ref(po: str) -> str:
    return f"INV-{str(po or '').strip()}"


def next_amendment_seq(current_seq: Any) -> int:
    """The next append-only amendment number under a PR (v1, v2, …). Starts at 1."""
    try:
        n = int(current_seq or 0)
    except (TypeError, ValueError):
        n = 0
    return max(1, n + 1)


def amendment_label(pr_id: str, seq: int) -> str:
    return f"{str(pr_id or '').strip()}#v{max(1, int(seq or 1))}"


def should_rotate(*, explicit_new: bool = False, finalized: bool = False,
                  idle_seconds: Optional[float] = None,
                  idle_ttl_seconds: int = DEFAULT_IDLE_TTL_SECONDS) -> bool:
    """Whether a NEW PR should be minted instead of amending the current one. Rotate on an explicit 'new order'
    / cart-clear, OR once the prior order is finalized (placed), OR when the cart has been idle past the TTL
    (so a stale cart can't capture an unrelated future order). Amendments while a cart is active do NOT rotate."""
    if explicit_new or finalized:
        return True
    if idle_seconds is not None and idle_ttl_seconds and float(idle_seconds) > float(idle_ttl_seconds):
        return True
    return False


def _iso_delta_seconds(earlier_iso: str, later_iso: str) -> Optional[float]:
    """Seconds between two ISO timestamps (space- or T-separated), or None if either is unparseable."""
    from datetime import datetime
    try:
        a = datetime.fromisoformat(str(earlier_iso).strip())
        b = datetime.fromisoformat(str(later_iso).strip())
        return (b - a).total_seconds()
    except (TypeError, ValueError):
        return None


def resolve_pr(active_pr: Optional[Dict[str, Any]], *, tenant_id: str, buyer_key: str, now_iso: str,
               nonce: str, explicit_new: bool = False,
               idle_ttl_seconds: int = DEFAULT_IDLE_TTL_SECONDS) -> Dict[str, Any]:
    """PURE resolution of the buyer's ACTIVE Procurement Request from its stored state (the caller does the
    session-memory I/O). Reuses the current PR across amendments; mints a fresh one only when there is none, or
    ``should_rotate`` fires (explicit-new / finalized / idle past TTL). Returns the new active-PR state
    {pr_id, opened_at, last_activity, finalized?}. This is what closes the cross-order-contamination bug: a
    genuinely new cart (after idle/finalize/explicit-new) gets a DISTINCT pr_id, while rapid amendments keep
    the SAME one (no churn)."""
    cur = active_pr if isinstance(active_pr, dict) else {}
    cur_id = cur.get("pr_id")
    last = cur.get("last_activity") or cur.get("opened_at")
    idle = _iso_delta_seconds(last, now_iso) if (cur_id and last) else None
    rotate = (not cur_id) or should_rotate(explicit_new=explicit_new, finalized=bool(cur.get("finalized")),
                                           idle_seconds=idle, idle_ttl_seconds=idle_ttl_seconds)
    if rotate:
        pr_id = mint_pr_id(tenant_id=tenant_id, buyer_key=buyer_key, opened_at_iso=now_iso, nonce=nonce)
        return {"pr_id": pr_id, "opened_at": now_iso, "last_activity": now_iso}
    return {**cur, "last_activity": now_iso, "finalized": False}


def mark_finalized(active_pr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flag the active PR as finalized (order placed) so the NEXT resolve rotates to a fresh PR. Pure."""
    cur = active_pr if isinstance(active_pr, dict) else {}
    return {**cur, "finalized": True}
