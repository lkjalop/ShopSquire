"""Multi-line procurement split planning.

The fulfillment case/draft domain is currently one commercial scope per case:
``{item_ref, quantity}``. For mixed buyer requests, the safe behavior is therefore
to split the request into one sourcing line per SKU and group those lines by the
approved supplier that would receive the RFQ. This module is read-only planning:
it never contacts a supplier and never creates a PO.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.order_split")

# connectors that separate order lines: "15 laptops + 10 monitors, and 5 headsets"
_LINE_SEP = re.compile(r"\s*(?:,|\+|;|\band\b)\s*", re.IGNORECASE)
# a line = a count (2..500, a bulk line) then up to TWO adjective words then a PLURAL noun, so "20 gaming
# laptops" / "10 wireless mechanical keyboards" parse (the adjective no longer breaks the count↔noun link).
# The plural noun is the LAST captured word; time/currency nouns are excluded. Vertical-blind.
_QTY_NOUN = re.compile(r"\b(\d{1,4})\s+(?:[a-z][a-z/\-]{2,}\s+){0,2}([a-z][a-z/\-]{2,}s)\b", re.IGNORECASE)
_NOT_PRODUCT_NOUNS = {"days", "weeks", "months", "years", "hours", "dollars", "units", "items",
                      "pieces", "pcs", "options", "results", "ones", "things"}


def parse_order_lines(query: str) -> List[Dict[str, Any]]:
    """Extract a mixed order — "15 laptops + 10 monitors + 5 headsets" → [{phrase, quantity}] — by splitting
    on connectors and reading a count + plural noun per segment. Agnostic: pure number + noun; the phrase is
    mapped to a SKU downstream. Time/currency nouns are never read as a line. Empty when no lines parse."""
    out: List[Dict[str, Any]] = []
    for seg in _LINE_SEP.split(str(query or "").lower()):
        m = _QTY_NOUN.search(seg)
        if not m:
            continue
        qty = int(m.group(1))
        noun = m.group(2).strip()
        if 1 < qty <= 500 and noun not in _NOT_PRODUCT_NOUNS:
            out.append({"phrase": noun, "quantity": qty})
    return out


def _load_active_products(db) -> List[Any]:
    """Fetch the ACTIVE catalog (sku, name, specs) ONCE so phrase→SKU matching is in-memory — no N+1 full
    scan per phrase. [] on any failure. Vertical-blind (opaque product DATA)."""
    if db is None:
        return []
    try:  # name + specs (the type word — "laptop"/"monitor" — is in the name); robust to a missing category col
        return list(db.execute(text("SELECT sku, name, specs FROM products WHERE active IS NOT FALSE")).fetchall())
    except Exception as exc:
        logger.debug("_load_active_products query failed: %s", exc)
        return []


def _match_sku_for_phrase(rows: List[Any], phrase: str) -> Optional[str]:
    """A representative SKU whose name/specs match the phrase (crude singularise), matched against PRE-FETCHED
    rows — pure, no DB. None if nothing matches."""
    token = str(phrase or "").strip().lower().rstrip("s")
    if not token:
        return None
    for r in (rows or []):
        blob = f"{str(r[1] or '')} {str(r[2] or '')}".lower()
        if token in blob:
            return str(r[0])
    return None


def _find_sku_for_phrase(db, phrase: str) -> Optional[str]:
    """Single-phrase convenience (one catalog fetch). In LOOPS prefer _load_active_products once +
    _match_sku_for_phrase per phrase (resolve_line_skus does this) to avoid the N+1."""
    return _match_sku_for_phrase(_load_active_products(db), phrase)


def _resolve_lines(db, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Core resolution: map parsed {phrase, quantity} lines to {item_ref, requested_qty}. NEVER silently loses
    a line or a quantity:
      • two phrases that resolve to the SAME sku → quantities are SUMMED (not the second dropped) — the buyer
        ordered 15, they get 15 (closes D1);
      • a phrase that resolves to NO sku is collected in ``unresolved`` (not dropped) so the caller can ask the
        buyer to clarify (closes L5).
    Catalog fetched at most once (lazy). Returns {resolved:[...], unresolved:[{phrase, quantity}]}."""
    resolved: List[Dict[str, Any]] = []
    by_sku: Dict[str, int] = {}      # sku -> index in resolved, for sum-on-collision
    unresolved: List[Dict[str, Any]] = []
    _rows: Optional[List[Any]] = None
    for ln in (lines or []):
        ir = str(ln.get("item_ref") or ln.get("sku") or "").strip()
        if not ir:
            if _rows is None:
                _rows = _load_active_products(db)  # one fetch, reused for every phrase
            ir = _match_sku_for_phrase(_rows, str(ln.get("phrase") or "")) or ""
        qty = _int(ln.get("requested_qty", ln.get("quantity")))
        source_qty = _int(ln.get("source_qty", ln.get("shortfall")))
        if qty <= 0:
            continue  # a zero/negative-qty line carries no order — genuinely empty, not a loss
        if not ir:
            unresolved.append({"phrase": ln.get("phrase"), "quantity": qty})  # SURFACE, never drop
            continue
        if ir in by_sku:
            resolved[by_sku[ir]]["requested_qty"] += qty                       # SUM, never drop
            if source_qty > 0:
                resolved[by_sku[ir]]["source_qty"] = _int(resolved[by_sku[ir]].get("source_qty")) + source_qty
        else:
            by_sku[ir] = len(resolved)
            line = {"item_ref": ir, "requested_qty": qty, "in_stock": _int(ln.get("in_stock")),
                    "phrase": ln.get("phrase")}
            if isinstance(ln.get("availability"), dict):
                line["availability"] = dict(ln["availability"])
            if source_qty > 0:
                line["source_qty"] = source_qty
            resolved.append(line)
    return {"resolved": resolved, "unresolved": unresolved}


def product_names(db, skus) -> Dict[str, str]:
    """{sku: display name} for the given SKUs — buyer-facing labels so a sourcing preview shows the product
    NAME, not a raw code like 'GAM-0006'. Opaque product DATA (vertical-blind); one catalog fetch. {} on any
    failure (the caller falls back to the SKU)."""
    want = {str(s) for s in (skus or []) if s}
    if not want:
        return {}
    out: Dict[str, str] = {}
    for r in _load_active_products(db):
        s = str(r[0])
        if s in want and r[1]:
            out[s] = str(r[1])
    return out


def resolve_line_skus(db, lines: List[Dict[str, Any]], *, tenant_id: str = "default") -> List[Dict[str, Any]]:
    """Resolved {item_ref, requested_qty} lines (back-compat shape). Sum-on-collision (no qty loss); unresolved
    phrases are surfaced via resolve_line_skus_detailed — use that when you need to clarify with the buyer."""
    return _resolve_lines(db, lines)["resolved"]


def resolve_line_skus_detailed(db, lines: List[Dict[str, Any]], *, tenant_id: str = "default") -> Dict[str, Any]:
    """Both halves: {resolved:[{item_ref, requested_qty, ...}], unresolved:[{phrase, quantity}]}. The caller
    surfaces ``unresolved`` so no buyer-stated line is silently dropped."""
    return _resolve_lines(db, lines)


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _supplier_rows(db, sku: str, limit: int = 5) -> List[Dict[str, Any]]:
    if db is None or not sku:
        return []
    try:
        from src.app.services.supplier_catalog import ensure_tables
        ensure_tables(db)
        rows = db.execute(text(
            "SELECT s.id, s.name, s.unit_cost, "
            "COALESCE(sp.lead_time_days, s.lead_time_days, 999) AS lead_time_days, "
            "COALESCE(sp.on_time_rate, s.on_time_rate, 0) AS on_time_rate, "
            "COALESCE(s.reliability_score, 0) AS reliability_score, "
            "COALESCE(sp.active,1) AS product_active, COALESCE(s.active,1) AS supplier_active "
            "FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
            "WHERE sp.sku = :sku AND COALESCE(sp.active,1)=1 AND COALESCE(s.active,1)=1 "
            "ORDER BY (COALESCE(sp.on_time_rate, s.on_time_rate, 0) * 0.45 "
            "       + COALESCE(s.reliability_score, 0) * 0.35 "
            "       - COALESCE(sp.lead_time_days, s.lead_time_days, 999) * 0.01 "
            "       - COALESCE(s.unit_cost, 0) * 0.00001) DESC "
            "LIMIT :limit"
        ), {"sku": str(sku), "limit": int(limit)}).fetchall()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append({
            "supplier_id": str(r[0]),
            "supplier_name": str(r[1] or r[0]),
            "unit_cost": r[2],
            "lead_time_days": _int(r[3]),
            "on_time_rate": float(r[4] or 0.0),
            "reliability": float(r[5] or 0.0),
        })
    return out


def _contact_for_domain(domain: str, *, tenant_id: str = "default") -> Optional[str]:
    try:
        from src.app.security.kyv_registry import lookup_vendor_by_domain
        v = lookup_vendor_by_domain(tenant_id=tenant_id, domain=domain) or {}
        email = str(v.get("contact_email") or "").strip()
        if email and email.lower().endswith(f"@{domain.lower()}"):
            return email
    except Exception as exc:
        logger.debug("contact lookup failed for %s: %s", domain, exc)
    return None


def plan_order_split(db, *, lines: List[Dict[str, Any]], tenant_id: str = "default") -> Dict[str, Any]:
    """Plan a mixed procurement request into supplier groups.

    Input lines are vertical-blind dictionaries containing ``item_ref``,
    ``requested_qty`` and optional ``in_stock``. The output is buyer/admin safe:
    each sourcing line carries the approved supplier selected from the catalog
    and the terms the operator needs to judge MOQ/min-value/price-break risk.
    """
    from src.app.services import supplier_catalog

    groups: Dict[str, Dict[str, Any]] = {}
    line_out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(lines or []):
        item_ref = str(raw.get("item_ref") or raw.get("sku") or "").strip()
        requested = max(0, _int(raw.get("requested_qty", raw.get("quantity")), 0))
        in_stock = max(0, _int(raw.get("in_stock"), 0))
        explicit_source = None
        if raw.get("source_qty") is not None:
            explicit_source = _int(raw.get("source_qty"), 0)
        elif raw.get("shortfall") is not None:
            explicit_source = _int(raw.get("shortfall"), 0)
        shortfall = max(0, min(requested, explicit_source)) if explicit_source is not None else max(0, requested - in_stock)
        line = {
            "line_id": str(raw.get("line_id") or f"line-{idx + 1}"),
            "item_ref": item_ref,
            "requested_qty": requested,
            "in_stock": in_stock,
            "shortfall": shortfall,
            "status": "fillable_from_stock" if shortfall <= 0 else "needs_sourcing",
        }
        if isinstance(raw.get("availability"), dict):
            line["availability"] = dict(raw["availability"])
        if shortfall <= 0 or not item_ref:
            line_out.append(line)
            continue

        ranked = _supplier_rows(db, item_ref, limit=3)
        if not ranked:
            line.update({"status": "no_approved_supplier", "supplier_candidates": []})
            line_out.append(line)
            continue

        best = ranked[0]
        sid = best["supplier_id"]
        domain = supplier_catalog.domain_for_supplier(db, sid)
        terms = supplier_catalog.supplier_terms(db, sid, item_ref, tenant_id=tenant_id)
        advisory = supplier_catalog.price_break_advisory(shortfall, terms)
        contact = _contact_for_domain(domain or "", tenant_id=tenant_id) if domain else None
        line.update({
            "supplier_ref": sid,
            "supplier_name": best["supplier_name"],
            "recipient_domain": domain,
            "recipient_email": contact,
            "supplier_terms": terms,
            "below_moq": bool(terms.get("moq") and shortfall < _int(terms.get("moq"))),
            "price_break_advisory": advisory,
            "supplier_candidates": ranked,
        })
        group_key = f"{sid}:{domain or ''}"
        group = groups.setdefault(group_key, {
            "group_id": group_key,
            "supplier_ref": sid,
            "supplier_name": best["supplier_name"],
            "recipient_domain": domain,
            "recipient_email": contact,
            "case_model": "one_case_per_sku",
            "lines": [],
            "total_shortfall": 0,
        })
        group["lines"].append(line)
        group["total_shortfall"] += shortfall
        line_out.append(line)

    return {
        "line_count": len(line_out),
        "sourcing_line_count": sum(1 for l in line_out if l.get("status") == "needs_sourcing"),
        "group_count": len(groups),
        "case_model": "one_case_per_sku_or_supplier_group",
        "groups": list(groups.values()),
        "lines": line_out,
    }


def emit_split_trace(trace_id: Optional[str], *, plan: Dict[str, Any]) -> None:
    if not trace_id:
        return
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            trace_id=trace_id,
            event_type="procurement_order_split",
            source_type="agent",
            source_id="Procurement_Split_Agent",
            target_type="procurement_order",
            target_id=None,
            payload={
                "line_count": plan.get("line_count"),
                "sourcing_line_count": plan.get("sourcing_line_count"),
                "group_count": plan.get("group_count"),
                "groups": [
                    {
                        "supplier_ref": g.get("supplier_ref"),
                        "recipient_domain": g.get("recipient_domain"),
                        "line_count": len(g.get("lines") or []),
                        "total_shortfall": g.get("total_shortfall"),
                    }
                    for g in (plan.get("groups") or [])
                ],
            },
            durable=True,
        )
    except Exception as exc:
        logger.debug("emit_split_trace failed: %s", exc)


def create_grouped_cases(db, *, plan: Dict[str, Any], uid: Optional[str] = None,
                         uid_hash: Optional[str] = None, trace_id: Optional[str] = None,
                         order_group_id: Optional[str] = None, now_iso: Optional[str] = None,
                         requirements: Optional[Dict[str, Any]] = None,
                         tenant_id: str = "default") -> Dict[str, Any]:
    """Turn a split plan into REAL cases — ONE procurement case per supplier group (the case carries the
    group's order_lines, so its RFQ lists every SKU). Reuses the single-case machinery + GATE 1 (each case
    waits at AWAITING_BUYER_COMMITMENT; no supplier is contacted). All cases share one order_group_id so the
    admin can show "create N cases across the buyer's mixed order". Best-effort per group; never raises."""
    import uuid as _uuid
    from src.app.services.fulfillment import workflow as fwf
    from src.app.services.fulfillment.domain import Actor, ActorType
    agent = Actor(ActorType.AGENT, "Procurement_Agent")
    group_id = str(order_group_id or f"order-{_uuid.uuid4().hex[:10]}")
    created: List[Dict[str, Any]] = []
    for g in (plan.get("groups") or []):
        lines = [l for l in (g.get("lines") or []) if isinstance(l, dict) and l.get("item_ref")]
        if not lines:
            continue
        order_lines = [{"item_ref": str(l["item_ref"]), "quantity": _int(l.get("requested_qty")),
                        "shortfall": _int(l.get("shortfall"))} for l in lines]
        total_qty = sum(int(l["quantity"]) for l in order_lines)
        total_short = sum(int(l["shortfall"]) for l in order_lines)
        try:
            cid = fwf.open_case(db, buyer_uid_hash=(uid_hash or uid), source_trace_id=trace_id,
                                requested_by="recommend", tenant_id=tenant_id)
            if not cid:
                continue
            line_availability = [
                dict(l.get("availability") or {}) for l in lines if isinstance(l.get("availability"), dict)]
            patch = {"availability": {"requested_qty": total_qty, "shortfall": total_short,
                                      "in_stock": max(0, total_qty - total_short),
                                      "item_ref": order_lines[0]["item_ref"],
                                      "lines": line_availability},
                     "order_group_id": group_id, "order_lines": order_lines,
                     "supplier_ref": g.get("supplier_ref"), "recipient_domain": g.get("recipient_domain")}
            if requirements:
                patch["requirements"] = requirements  # buyer deadline/use_case/ship_to → cited in the RFQ (concrete deadline)
            assessed = fwf.transition(
                db, case_id=cid, event="availability_assessed", actor=agent,
                reason_code="multi_line_order", state_patch=patch, trace_id=trace_id,
                now_iso=now_iso, tenant_id=tenant_id,
            )
            if not assessed.ok:
                raise RuntimeError(
                    f"availability_assessed_failed:{assessed.reason}"
                )
            awaiting = fwf.transition(
                db, case_id=cid, event="request_buyer_commitment", actor=agent,
                trace_id=trace_id, now_iso=now_iso, tenant_id=tenant_id,
            )
            if not awaiting.ok:
                raise RuntimeError(
                    f"request_buyer_commitment_failed:{awaiting.reason}"
                )
            created.append({"case_id": cid, "supplier_ref": g.get("supplier_ref"),
                            "supplier_name": g.get("supplier_name"), "recipient_domain": g.get("recipient_domain"),
                            "lines": order_lines, "total_quantity": total_qty})
        except Exception as exc:
            db.rollback()
            logger.warning(
                "create_grouped_cases: group %s failed: %s",
                g.get("group_id"),
                exc,
            )
    try:
        db.commit()
    except Exception as exc:
        logger.debug("create_grouped_cases commit failed: %s", exc)
    return {"order_group_id": group_id, "case_count": len(created), "cases": created}
