"""Supplier_Inbox_Reader — bounded, read-only supplier-history context for a draft.

Proves the summary synthesis (last invoice / prior messages / contact), that it returns None when
nothing is known (so no empty evidence is added), and that the draft gathers a SUP-HIST evidence item
ONLY when context exists — keyed on the allowlist-resolved domain, never buyer text.
"""
from __future__ import annotations

from src.app.services import supplier_inbox_reader as sir


def _hist(*amounts):
    return lambda domain, window, tenant: [
        {"event_ts": f"2026-06-2{i}T10:00:00", "invoice_amount": a} for i, a in enumerate(amounts, start=1)
    ]


# ── reader synthesis ──────────────────────────────────────────────────────────
def test_context_from_history_and_contact():
    ctx = sir.recent_supplier_context(
        domain="approved-supplier.example",
        history_fn=_hist(1100.0, 1180.0),
        contact_fn=lambda d, t: "sales@approved-supplier.example")
    assert ctx is not None
    assert ctx.observations == 2 and ctx.last_invoice_cents == 118000  # last amount × 100
    assert ctx.contact_email == "sales@approved-supplier.example"
    s = ctx.summary()
    assert "last invoice ~1180" in s and "2 prior message(s)" in s and "contact sales@" in s


def test_returns_none_when_nothing_known():
    ctx = sir.recent_supplier_context(domain="unknown.example",
                                      history_fn=lambda d, w, t: [], contact_fn=lambda d, t: None)
    assert ctx is None


def test_contact_only_is_enough():
    ctx = sir.recent_supplier_context(domain="x.example", history_fn=lambda d, w, t: [],
                                      contact_fn=lambda d, t: "ap@x.example")
    assert ctx is not None and ctx.observations == 0 and ctx.contact_email == "ap@x.example"


def test_blank_domain_is_none():
    assert sir.recent_supplier_context(domain="") is None


def test_to_dict_carries_summary():
    ctx = sir.recent_supplier_context(domain="x.example", history_fn=_hist(900.0),
                                      contact_fn=lambda d, t: None)
    d = ctx.to_dict()
    assert d["domain"] == "x.example" and d["last_invoice_cents"] == 90000 and "summary" in d


# ── draft wiring (the 5th evidence source) ───────────────────────────────────
def test_draft_adds_supplier_history_evidence_when_known():
    from src.app.services.fulfillment.draft import gather_evidence
    inbox = lambda domain, tenant: {"summary": "last invoice ~1180; contact ap@s.example", "domain": domain}
    ev = gather_evidence(None, item_ref="LAP-021", recipient_domain="approved-supplier.example",
                         inbox_fn=inbox)
    hist = [e for e in ev if e.source == "supplier_history"]
    assert len(hist) == 1 and hist[0].evidence_id.startswith("SUP-HIST-")
    assert "1180" in hist[0].summary


def test_draft_adds_no_history_when_none():
    from src.app.services.fulfillment.draft import gather_evidence
    ev = gather_evidence(None, item_ref="LAP-021", recipient_domain="approved-supplier.example",
                         inbox_fn=lambda domain, tenant: None)
    assert not any(e.source == "supplier_history" for e in ev)


def test_draft_no_history_without_domain():
    from src.app.services.fulfillment.draft import gather_evidence
    ev = gather_evidence(None, item_ref="LAP-021")  # no recipient_domain → reader not consulted
    assert not any(e.source == "supplier_history" for e in ev)


# ── MAESTRO boundary is registered + read-only ───────────────────────────────
def test_maestro_boundary_is_read_only():
    from src.app.security.maestro_boundaries import AGENT_BOUNDARIES
    b = AGENT_BOUNDARIES.get("Supplier_Inbox_Reader")
    assert b is not None
    assert b.can_write_db is False and b.can_call_external_api is False
    assert b.max_autonomous_value_usd == 0.0
