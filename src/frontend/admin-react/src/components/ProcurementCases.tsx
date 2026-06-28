/**
 * ProcurementCases — the operator control room for auditable procurement (orchestrator).
 *
 * Owns the case state + handlers and composes the extracted pieces:
 *   procurement/CaseQueue          — searchable/filterable case queue
 *   procurement/ActionBar          — the state-driven workflow buttons (one button = one transition)
 *   procurement/SupplierDraftPacket — the supplier-email approval packet (recipient/scope/gate/evidence/edit)
 *   procurement/QuotePacket        — parsed quote + the resulting PO
 *   procurement/CaseJourney        — bitemporal time-travel (as-of) + the transition journey
 * The two gates (buyer commitment, human send) are enforced by the backend workflow; this UI only offers
 * what the case's state permits and surfaces the bitemporal trace.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  fcCaseAsOf, fcCaseOkf, fcCompareQuotes, fcEconomics, fcEditDraft, fcRfqFanout, fcSupplierCandidates,
  getFulfillmentCaseOp, getFulfillmentJourney, listFulfillmentCases,
  type DealEconomics, type FulfillmentCaseRow, type FulfillmentCaseView, type JourneyEvent,
  type RfqFanoutDraft, type SupplierCandidate,
} from '../api';
import ActionBar from './procurement/ActionBar';
import AutonomyAudit from './procurement/AutonomyAudit';
import CaseJourney from './procurement/CaseJourney';
import CaseQueue from './procurement/CaseQueue';
import QuotePacket from './procurement/QuotePacket';
import RfqFanout from './procurement/RfqFanout';
import SupplierCandidates from './procurement/SupplierCandidates';
import SupplierDraftPacket from './procurement/SupplierDraftPacket';

const dollars = (c?: number) => (c == null ? '—' : `$${(c / 100).toFixed(2)}`);
const pct = (r?: number) => (r == null ? '—' : `${(r * 100).toFixed(1)}%`);

export function ProcurementCases() {
  const [cases, setCases] = useState<FulfillmentCaseRow[]>([]);
  const [sel, setSel] = useState<string>('');
  const [view, setView] = useState<FulfillmentCaseView | null>(null);
  const [journey, setJourney] = useState<JourneyEvent[]>([]);
  const [scenario, setScenario] = useState('full_quote');
  const [econ, setEcon] = useState<DealEconomics | null>(null);
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');
  const [asOfT, setAsOfT] = useState('');
  const [asOf, setAsOf] = useState<{ as_of: string; state: string } | null>(null);
  const [candidates, setCandidates] = useState<SupplierCandidate[]>([]);
  const [fanout, setFanout] = useState<RfqFanoutDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(() => {
    listFulfillmentCases().then(setCases).catch((e) => setError(e.message));
  }, []);
  const loadCase = useCallback((id: string) => {
    if (!id) return;
    setEcon(null); setAsOf(null); setCandidates([]); setFanout([]);  // per-case panels — clear when switching
    Promise.all([getFulfillmentCaseOp(id), getFulfillmentJourney(id)])
      .then(([v, j]) => { setView(v); setJourney(j); setError(null); })
      .catch((e) => setError(e.message));
    // supplier shortlist (read-only review prefill) — best-effort, never blocks the case view
    fcSupplierCandidates(id).then((r) => setCandidates(r.candidates || [])).catch(() => setCandidates([]));
    // competitive RFQ fan-out preview (caged drafts per top-N supplier) — best-effort, never sends
    fcRfqFanout(id).then((r) => setFanout(r.drafts || [])).catch(() => setFanout([]));
  }, []);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { if (sel) loadCase(sel); }, [sel, loadCase]);

  const draft = (view?.state_json?.draft || {}) as Record<string, any>;
  const parsed = (view?.state_json?.parsed_quote || view?.state_json?.validated_quote || {}) as Record<string, any>;
  const inbound = (view?.state_json?.inbound || {}) as Record<string, any>;
  const po = (view?.state_json?.purchase_order || {}) as Record<string, any>;
  const availability = (view?.state_json?.availability || {}) as Record<string, any>;
  const state = view?.state || '';
  const draftChanged = Boolean(draft.subject || draft.body)
    && (editSubject !== String(draft.subject || '') || editBody !== String(draft.body || ''));
  const draftEvidence = Array.isArray(draft.evidence) ? draft.evidence : [];
  const recipientDisplay = draft.recipient_email || draft.recipient_domain || 'not resolved';
  const draftItemRef = String(draft.commercial_scope?.item_ref || availability.item_ref || '').trim();
  const draftQty = Number(draft.commercial_scope?.quantity || availability.shortfall || availability.requested_qty || 0);
  // keep the editable draft fields in sync with the persisted draft (re-syncs after an edit re-hashes).
  useEffect(() => { setEditSubject(draft.subject || ''); setEditBody(draft.body || ''); }, [draft.content_hash]);
  const humanGate = state === 'AWAITING_APPROVAL' || state === 'PROCUREMENT_APPROVAL_REQUIRED';
  const isDemoReply = String(inbound.provider_ref || '').startsWith('DEMO-')
    || String(inbound.sender_domain || '').endsWith('.example');

  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setError(null);
    try { await fn(); loadCase(sel); loadList(); }
    catch (e: any) { setError(e?.message || 'action failed'); }
    finally { setBusy(false); }
  };

  const onEconomics = () => fcEconomics(sel)
    .then((e) => setEcon((e as DealEconomics)?.margin_pct != null ? (e as DealEconomics) : null))
    .catch((er: any) => setError(er?.message || 'economics failed'));
  const onReconstruct = () => fcCaseAsOf(sel, asOfT)
    .then((v) => setAsOf({ as_of: v.as_of, state: v.state }))
    .catch((e: any) => setError(e?.message || 'as-of failed'));
  const onExportOkf = () => fcCaseOkf(sel)
    .then((d) => {
      const blob = new Blob([d.okf], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = d.filename || `procurement-${sel.slice(0, 8)}.md`;
      a.click(); URL.revokeObjectURL(url);
    })
    .catch((e: any) => setError(e?.message || 'okf export failed'));

  return (
    <div className="procurement-cases" data-testid="procurement-cases">
      <AutonomyAudit />
      <div style={{ display: 'flex', gap: 16 }}>
        <CaseQueue cases={cases} sel={sel} onSelect={setSel} onRefresh={loadList} />

        {view && (
          <section style={{ flex: 1 }}>
            <h3>{sel.slice(0, 8)} — <span data-testid="op-state">{state}</span>
              {humanGate && (
                <span data-testid="op-human-gate"
                      style={{ marginLeft: 8, padding: '2px 6px', background: '#fde68a', color: '#7c2d12',
                               borderRadius: 4, fontSize: 12, fontWeight: 700 }}>
                  HUMAN APPROVAL REQUIRED
                </span>
              )}
            </h3>
            {error && <p role="alert" style={{ color: 'crimson' }}>{error}</p>}
            {state === 'NO_APPROVED_SUPPLIER' && (
              <div data-testid="op-no-supplier-banner" role="alert"
                   style={{ margin: '8px 0', padding: '8px 10px', borderRadius: 8, border: '1px solid #f87171',
                            background: '#fef2f2', color: '#991b1b' }}>
                <strong>No approved supplier for this SKU.</strong> Seed or approve a supplier
                (<code>scripts/seed_suppliers.py</code>, or add a trusted domain) before contacting the buyer —
                the draft cannot be generated until coverage exists.
              </div>
            )}

            {/* Supplier shortlist (read-only review prefill) — most useful before/at drafting. */}
            {(state === 'COMMITTED' || state === 'NO_APPROVED_SUPPLIER' || state === 'QUOTE_DRAFTED') && (
              <SupplierCandidates candidates={candidates} />
            )}

            {/* Competitive RFQ (multi-supplier): caged draft preview per top-N supplier + quote compare. */}
            {(state === 'COMMITTED' || state === 'QUOTE_DRAFTED') && fanout.length > 0 && (
              <RfqFanout drafts={fanout} onCompare={(quotes) => fcCompareQuotes(sel, quotes)} />
            )}

            <ActionBar sel={sel} state={state} busy={busy} draftItemRef={draftItemRef} draftQty={draftQty}
                       draftChanged={draftChanged} draftHash={draft.content_hash} scenario={scenario}
                       setScenario={setScenario} run={run} onEconomics={onEconomics} />

            {econ && (
              <details open data-testid="op-economics-panel">
                <summary>Deal economics (operator-only) — margin {pct(econ.margin_pct)}</summary>
                <div>Supplier charges us {dollars(econ.supplier_cost_cents)} ({dollars(econ.supplier_unit_cost_cents)}/unit × {econ.quantity})</div>
                <div>We list at {dollars(econ.retail_cents)} → gross profit <strong>{dollars(econ.gross_profit_cents)}</strong> ({pct(econ.margin_pct)})</div>
                <div>Buyer discount headroom: up to <strong>{dollars(econ.max_buyer_discount_cents)}</strong> ({pct(econ.max_buyer_discount_pct)}) and still clear the {pct(econ.floor_margin_pct)} floor</div>
                <div>Profit if we give the full discount: {dollars(econ.profit_after_max_discount_cents)}</div>
                {!econ.clears_floor && <div style={{ color: 'crimson' }}>⚠ list margin is below the floor — no discount headroom</div>}
              </details>
            )}

            <SupplierDraftPacket draft={draft} state={state} recipientDisplay={recipientDisplay}
                                 draftEvidence={draftEvidence} draftChanged={draftChanged}
                                 editSubject={editSubject} setEditSubject={setEditSubject}
                                 editBody={editBody} setEditBody={setEditBody} busy={busy}
                                 onSaveEdit={() => run(() => fcEditDraft(sel, editSubject, editBody))} />

            <QuotePacket parsed={parsed} po={po} isDemoReply={isDemoReply} />

            <CaseJourney journey={journey} asOfT={asOfT} setAsOfT={setAsOfT} asOf={asOf}
                         onReconstruct={onReconstruct} busy={busy} onExportOkf={onExportOkf} />
          </section>
        )}
      </div>
    </div>
  );
}

export default ProcurementCases;
