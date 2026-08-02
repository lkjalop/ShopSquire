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
  fcCaseAsOf, fcCaseOkf, fcCompareQuotes, fcEconomics, fcEditDraft, fcQuarantineDisposition,
  fcRfqFanout, fcSupplierCandidates,
  getFulfillmentCaseOp, getFulfillmentJourneyView, listFulfillmentCases,
  type CommunicationEvent, type DealEconomics, type FulfillmentCaseRow, type FulfillmentCaseView, type JourneyEvent,
  type RfqFanoutDraft, type SupplierCandidate,
} from '../api';
import ActionBar from './procurement/ActionBar';
import AllocationWorkbench from './procurement/AllocationWorkbench';
import AutonomyAudit from './procurement/AutonomyAudit';
import CreateFromOrder from './procurement/CreateFromOrder';
import ProcurementNotifications from './procurement/ProcurementNotifications';
import { procurementActionMessage } from '../lib/actionError';
import CaseJourney from './procurement/CaseJourney';
import CaseQueue from './procurement/CaseQueue';
import DecisionIntelligence from './procurement/DecisionIntelligence';
import ForecastEvidence from './procurement/ForecastEvidence';
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
  const [communications, setCommunications] = useState<CommunicationEvent[]>([]);
  const [communicationStatus, setCommunicationStatus] = useState('unavailable');
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
    Promise.all([getFulfillmentCaseOp(id), getFulfillmentJourneyView(id)])
      .then(([v, activity]) => {
        setView(v);
        setJourney(activity.journey);
        setCommunications(activity.communications);
        setCommunicationStatus(activity.communication_status);
        setError(null);
      })
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
  const quarantine = (view?.state_json?.quarantine || {}) as Record<string, any>;
  const quarantineEvent = [...journey].reverse().find((event) => event.event === 'supplier_response_quarantined');
  const po = (view?.state_json?.purchase_order || {}) as Record<string, any>;
  const availability = (view?.state_json?.availability || {}) as Record<string, any>;
  const state = view?.state || '';
  const draftChanged = Boolean(draft.subject || draft.body)
    && (editSubject !== String(draft.subject || '') || editBody !== String(draft.body || ''));
  const draftEvidence = Array.isArray(draft.evidence) ? draft.evidence : [];
  const recipientDisplay = draft.recipient_email || draft.recipient_domain || 'not resolved';
  const draftItemRef = String(draft.commercial_scope?.item_ref || availability.item_ref || '').trim();
  const draftQty = Number(draft.commercial_scope?.quantity || availability.shortfall || availability.requested_qty || 0);
  const forecastLeadTime = Number(
    candidates.find((candidate) => candidate.recommended)?.lead_time_days
    || candidates[0]?.lead_time_days
    || 14,
  );
  // keep the editable draft fields in sync with the persisted draft (re-syncs after an edit re-hashes).
  useEffect(() => { setEditSubject(draft.subject || ''); setEditBody(draft.body || ''); }, [draft.content_hash]);
  const humanGate = state === 'AWAITING_APPROVAL' || state === 'PROCUREMENT_APPROVAL_REQUIRED';
  const isDemoReply = String(inbound.provider_ref || '').startsWith('DEMO-')
    || String(inbound.sender_domain || '').endsWith('.example');

  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setError(null);
    try { await fn(); loadCase(sel); loadList(); }
    catch (e: any) {
      // a 409 (idempotent replay / state conflict) is benign — show a calm notice and refresh to the real
      // current state instead of a scary raw error (the 409-replay UX).
      const m = procurementActionMessage(e);
      setError(m.message);
      if (m.calm) { loadCase(sel); loadList(); }
    }
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
      <AllocationWorkbench />
      <AutonomyAudit />
      <ProcurementNotifications onActivity={loadList} />
      <CreateFromOrder onCreated={loadList} />
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
            {state === 'SUPPLIER_RESPONSE_QUARANTINED' && (
              <div data-testid="op-quarantine-panel" role="alert"
                   style={{ margin: '8px 0', padding: '10px 12px', borderRadius: 8,
                            border: '1px solid #f59e0b', background: '#fffbeb', color: '#78350f' }}>
                <strong>Supplier response quarantined</strong>
                <div data-testid="op-quarantine-reason">
                  Reason: {String(quarantine.reason || 'security review required').replace(/_/g, ' ')}
                </div>
                <div>Supplier: {quarantine.sender_domain || 'unknown'}</div>
                <div>Received: {quarantineEvent?.valid_from || 'timestamp unavailable'}</div>
                <div>
                  Evidence: {quarantine.security
                    ? `${quarantine.security.severity || 'unknown'} · ${quarantine.security.route || 'review'}`
                    : 'sender trust evidence recorded'}
                </div>
                <div data-testid="op-quarantine-evidence-ref">
                  Immutable evidence: {quarantine.raw_evidence_ref || 'reference unavailable'}
                </div>
                <div data-testid="op-quarantine-enrichment">
                  Enrichment: {view.email_enrichment?.status || 'not scheduled'}
                  {view.email_enrichment ? ` · ${view.email_enrichment.attempts || 0} attempt(s)` : ''}
                </div>
                {Array.isArray(quarantine.security?.reasons) && quarantine.security.reasons.length > 0 && (
                  <ul data-testid="op-quarantine-evidence">
                    {quarantine.security.reasons.map((reason: string, i: number) => (
                      <li key={i}>{String(reason).replace(/_/g, ' ')}</li>
                    ))}
                  </ul>
                )}
                <div data-testid="op-quarantine-actions" style={{ marginTop: 6, fontWeight: 600 }}>
                  Operator action: verify the supplier out-of-band, inspect the immutable evidence reference,
                  then keep the response quarantined or open a fresh RFQ. No quote, economics, PO, or payment
                  state was updated.
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <button disabled={busy} onClick={() => run(() =>
                    fcQuarantineDisposition(sel, 'keep_quarantined', 'Operator reviewed evidence'))}>
                    Keep quarantined
                  </button>
                  <button disabled={busy} onClick={() => {
                    if (window.confirm('Discard this response permanently? The evidence retention policy still applies.')) {
                      run(() => fcQuarantineDisposition(sel, 'discard', 'Operator discarded unsafe response'));
                    }
                  }}>
                    Discard response
                  </button>
                  <button disabled={busy} onClick={() => {
                    if (window.confirm('Open a fresh RFQ? The quarantined response will not be reused.')) {
                      run(() => fcQuarantineDisposition(sel, 'open_fresh_rfq', 'Fresh RFQ requested after quarantine'));
                    }
                  }}>
                    Open fresh RFQ
                  </button>
                </div>
                {(view.quarantine_dispositions || []).length > 0 && (
                  <div data-testid="op-quarantine-history" style={{ marginTop: 8 }}>
                    <strong>Disposition history</strong>
                    <ul>
                      {(view.quarantine_dispositions || []).map((item, i) => (
                        <li key={i}>
                          {item.action.replace(/_/g, ' ')} · {item.actor_id}
                          {item.created_at ? ` · ${item.created_at}` : ''}
                          {item.note ? ` — ${item.note}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Supplier shortlist (read-only review prefill) — most useful before/at drafting. */}
            {(state === 'COMMITTED' || state === 'NO_APPROVED_SUPPLIER' || state === 'QUOTE_DRAFTED') && (
              <SupplierCandidates candidates={candidates} />
            )}

            {draftItemRef && (
              <ForecastEvidence sku={draftItemRef} leadTimeDays={forecastLeadTime} />
            )}
            <DecisionIntelligence caseId={sel} />

            {/* Competitive RFQ (multi-supplier): caged draft preview per top-N supplier + quote compare. */}
            {(state === 'COMMITTED' || state === 'QUOTE_DRAFTED') && fanout.length > 0 && (
              <RfqFanout drafts={fanout} onCompare={(quotes) => fcCompareQuotes(sel, quotes)} />
            )}

            {/* SELL ENGINE: margin verdict + discount headroom auto-surfaced AT the send-decision gate, so
                the operator judges whether the reorder is worth it BEFORE approving the supplier send. */}
            {view?.margin_advice?.available && (
              <div data-testid="op-margin-advice"
                   style={{ margin: '8px 0', padding: '8px 10px', borderRadius: 8,
                            border: '1px solid ' + (view.margin_advice.verdict === 'below_floor' ? '#f87171'
                              : view.margin_advice.verdict === 'thin' ? '#fcd34d' : '#86efac'),
                            background: view.margin_advice.verdict === 'below_floor' ? '#fef2f2'
                              : view.margin_advice.verdict === 'thin' ? '#fffbeb' : '#f0fdf4' }}>
                <strong data-testid="op-margin-verdict">Margin: {view.margin_advice.verdict}</strong>
                {' — '}list margin {pct(view.margin_advice.economics?.margin_pct)} vs floor {pct(view.margin_advice.economics?.floor_margin_pct)}.
                {(view.margin_advice.recommended_buyer_discount_cents ?? 0) > 0 && (
                  <div>You can offer the buyer up to <strong>{dollars(view.margin_advice.recommended_buyer_discount_cents)}</strong>
                    {' '}and keep a safe margin (hard ceiling {dollars(view.margin_advice.max_buyer_discount_cents)}).</div>
                )}
                {view.margin_advice.supplier_last_invoice_cents != null && (
                  <div style={{ color: '#6b7280', fontSize: 12 }}>Last invoiced from this supplier ~{dollars(view.margin_advice.supplier_last_invoice_cents)}.</div>
                )}
                {view.margin_warning && (
                  <div data-testid="op-margin-warning" style={{ color: '#991b1b', fontWeight: 700, marginTop: 4 }}>
                    ⚠ {view.margin_warning.message}
                  </div>
                )}
                {view.margin_advice.sales_response && (
                  <div data-testid="op-sales-response" style={{ marginTop: 6, paddingTop: 6, borderTop: '1px dashed #d1d5db' }}>
                    <strong>Demand-aware call:</strong>{' '}
                    {view.margin_advice.sales_response.discount_action === 'increase'
                      ? `discount up to ${pct(view.margin_advice.sales_response.recommended_discount_pct)} to move stock`
                      : view.margin_advice.sales_response.discount_action === 'reduce'
                        ? 'hold/trim discount — protect margin'
                        : 'hold — no discount pressure'}
                    {' · '}reorder: {view.margin_advice.sales_response.reorder_urgency}
                    <div style={{ color: '#6b7280', fontSize: 12, marginTop: 2 }}>
                      {(view.margin_advice.sales_response.rationale || []).slice(0, 2).map((r: string, i: number) => (
                        <div key={i}>• {r}</div>
                      ))}
                      <div style={{ fontStyle: 'italic' }}>
                        demand {view.margin_advice.sales_response.situation?.demand_trend} · stock {view.margin_advice.sales_response.situation?.inventory_position} · margin {view.margin_advice.sales_response.situation?.margin_headroom}
                      </div>
                    </div>
                  </div>
                )}
              </div>
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

            <CaseJourney journey={journey} communications={communications}
                         communicationStatus={communicationStatus}
                         asOfT={asOfT} setAsOfT={setAsOfT} asOf={asOf}
                         onReconstruct={onReconstruct} busy={busy} onExportOkf={onExportOkf} />
          </section>
        )}
      </div>
    </div>
  );
}

export default ProcurementCases;
