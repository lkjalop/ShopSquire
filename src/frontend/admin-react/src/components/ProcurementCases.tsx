/**
 * ProcurementCases — the operator control room for auditable procurement.
 *
 * Composes the existing fulfilment API: list cases, open one, walk its journey, and drive the
 * operator/agent actions. Each button maps to ONE backend transition (the workflow enforces the
 * actor + the two gates), so the operator can only do what the case's state permits:
 *   COMMITTED            → Draft quote (agent) → Request approval (agent)
 *   AWAITING_APPROVAL    → Approve & send (HUMAN, GATE 2 — hash-checked)
 *   QUOTE_SENT           → Trigger supplier reply (DEMO) → parse
 *   QUOTE_RECEIVED       → Validate quote (HUMAN; expired hard-rejects)
 *   QUOTE_VALIDATED      → Generate options (agent)
 * The exact pending email + its content-hash, the parsed quote with evidence spans, and the full
 * bitemporal journey are all inspectable here.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  fcCompleteCase, fcDemoReply, fcDispatch, fcDraftQuote, fcEconomics, fcExecutePO, fcGenerateOptions,
  fcProposePO, fcRequestApproval, fcValidateQuote,
  getFulfillmentCaseOp, getFulfillmentJourney, listFulfillmentCases,
  type DealEconomics, type FulfillmentCaseRow, type FulfillmentCaseView, type JourneyEvent,
} from '../api';

const dollars = (c?: number) => (c == null ? '—' : `$${(c / 100).toFixed(2)}`);
const pct = (r?: number) => (r == null ? '—' : `${(r * 100).toFixed(1)}%`);

const SCENARIOS = ['full_quote', 'partial_availability', 'late_delivery', 'substitute_offer',
  'expired_quote', 'untrusted_sender', 'contradictory_quantity'];

export function ProcurementCases() {
  const [cases, setCases] = useState<FulfillmentCaseRow[]>([]);
  const [sel, setSel] = useState<string>('');
  const [view, setView] = useState<FulfillmentCaseView | null>(null);
  const [journey, setJourney] = useState<JourneyEvent[]>([]);
  const [scenario, setScenario] = useState('full_quote');
  const [econ, setEcon] = useState<DealEconomics | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(() => {
    listFulfillmentCases().then(setCases).catch((e) => setError(e.message));
  }, []);
  const loadCase = useCallback((id: string) => {
    if (!id) return;
    setEcon(null);  // economics is per-case — clear when switching
    Promise.all([getFulfillmentCaseOp(id), getFulfillmentJourney(id)])
      .then(([v, j]) => { setView(v); setJourney(j); setError(null); })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { if (sel) loadCase(sel); }, [sel, loadCase]);

  const draft = (view?.state_json?.draft || {}) as Record<string, any>;
  const parsed = (view?.state_json?.parsed_quote || view?.state_json?.validated_quote || {}) as Record<string, any>;
  const inbound = (view?.state_json?.inbound || {}) as Record<string, any>;
  const po = (view?.state_json?.purchase_order || {}) as Record<string, any>;
  const state = view?.state || '';
  // GATE 2 send + PO approval are the two HUMAN-only stops — surface them as a badge.
  const humanGate = state === 'AWAITING_APPROVAL' || state === 'PROCUREMENT_APPROVAL_REQUIRED';
  // the deterministic sandbox tags every reply with a DEMO-MSG- ref / .example sender (never real).
  const isDemoReply = String(inbound.provider_ref || '').startsWith('DEMO-')
    || String(inbound.sender_domain || '').endsWith('.example');

  const run = async (fn: () => Promise<any>) => {
    setBusy(true); setError(null);
    try { await fn(); loadCase(sel); loadList(); }
    catch (e: any) { setError(e?.message || 'action failed'); }
    finally { setBusy(false); }
  };

  return (
    <div className="procurement-cases" data-testid="procurement-cases">
      <div style={{ display: 'flex', gap: 16 }}>
        <aside style={{ minWidth: 280 }}>
          <h3>Procurement Cases <button onClick={loadList}>↻</button></h3>
          <table>
            <thead><tr><th>Case</th><th>Status</th></tr></thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_id} onClick={() => setSel(c.case_id)}
                    style={{ cursor: 'pointer', fontWeight: c.case_id === sel ? 700 : 400 }}>
                  <td>{c.case_id.slice(0, 8)}</td>
                  <td>{c.status?.replace(/_/g, ' ').toLowerCase()}</td>
                </tr>
              ))}
              {cases.length === 0 && <tr><td colSpan={2}><em>no cases</em></td></tr>}
            </tbody>
          </table>
        </aside>

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

            <div className="actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
              {state === 'COMMITTED' && (
                <>
                  <button disabled={busy} data-testid="op-draft"
                          onClick={() => run(() => fcDraftQuote(sel, draft.commercial_scope?.item_ref || 'SKU-1', 6))}>
                    Draft quote (agent)
                  </button>
                </>
              )}
              {state === 'QUOTE_DRAFTED' && (
                <button disabled={busy} data-testid="op-request-approval"
                        onClick={() => run(() => fcRequestApproval(sel))}>Request approval</button>
              )}
              {(state === 'AWAITING_APPROVAL' || state === 'APPROVED_TO_SEND') && (
                <button disabled={busy} data-testid="op-dispatch"
                        onClick={() => run(() => fcDispatch(sel, draft.content_hash || ''))}>
                  Approve &amp; send (GATE 2)
                </button>
              )}
              {state === 'QUOTE_SENT' && (
                <>
                  <select value={scenario} onChange={(e) => setScenario(e.target.value)} data-testid="op-scenario">
                    {SCENARIOS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <button disabled={busy} data-testid="op-demo-reply"
                          onClick={() => run(() => fcDemoReply(sel, scenario, 6))}>Trigger supplier reply</button>
                  <span style={{ fontSize: 11, color: '#b45309', fontWeight: 700 }}>SANDBOX SUPPLIER</span>
                </>
              )}
              {state === 'QUOTE_RECEIVED' && (
                <button disabled={busy} data-testid="op-validate"
                        onClick={() => run(() => fcValidateQuote(sel))}>Validate quote</button>
              )}
              {state === 'QUOTE_VALIDATED' && (
                <button disabled={busy} data-testid="op-options"
                        onClick={() => run(() => fcGenerateOptions(sel))}>Generate options</button>
              )}
              {state === 'SELECTED' && (
                <button disabled={busy} data-testid="op-propose-po"
                        onClick={() => run(() => fcProposePO(sel))}>Propose PO (agent)</button>
              )}
              {state === 'PROCUREMENT_APPROVAL_REQUIRED' && (
                <button disabled={busy} data-testid="op-execute-po"
                        onClick={() => run(() => fcExecutePO(sel, `po-${sel}`))}>
                  Approve &amp; create PO (HUMAN)
                </button>
              )}
              {(state === 'READY_TO_SHIP' || state === 'PARTIALLY_READY') && (
                <button disabled={busy} data-testid="op-complete"
                        onClick={() => run(() => fcCompleteCase(sel))}>Mark completed</button>
              )}
              {['SELECTED', 'PROCUREMENT_APPROVAL_REQUIRED', 'PROCUREMENT_IN_PROGRESS', 'READY_TO_SHIP',
                'PARTIALLY_READY', 'COMPLETED'].includes(state) && (
                <button disabled={busy} data-testid="op-economics"
                        onClick={() => fcEconomics(sel)
                          .then((e) => setEcon((e as DealEconomics)?.margin_pct != null ? (e as DealEconomics) : null))
                          .catch((er: any) => setError(er?.message || 'economics failed'))}>
                  Deal economics
                </button>
              )}
            </div>

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

            {draft.subject && (
              <details open>
                <summary>Outbound draft (content hash {String(draft.content_hash).slice(0, 8)})</summary>
                <div><strong>To:</strong> {draft.recipient_domain}</div>
                <div><strong>Subject:</strong> {draft.subject}</div>
                <pre style={{ whiteSpace: 'pre-wrap' }}>{draft.body}</pre>
                {Array.isArray(draft.rationale) && (
                  <ul>{draft.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
                )}
              </details>
            )}

            {parsed.quoted_quantity != null && (
              <details open>
                <summary>Parsed quote (confidence {parsed.confidence})
                  {isDemoReply && (
                    <span data-testid="op-demo-quote"
                          style={{ marginLeft: 8, padding: '1px 5px', background: '#dbeafe', color: '#1e3a8a',
                                   borderRadius: 4, fontSize: 11, fontWeight: 700 }}>
                      DEMO QUOTE RESPONSE
                    </span>
                  )}
                </summary>
                <div>Qty {parsed.quoted_quantity} · unit {parsed.unit_amount_cents} · dispatch {parsed.dispatch_ready_at} · expires {parsed.quote_expires_at}</div>
                {parsed.contradictory && <div style={{ color: 'orange' }}>⚠ contradictory quantity — review</div>}
                {Array.isArray(parsed.evidence_spans) && (
                  <ul>{parsed.evidence_spans.map((s: any, i: number) => <li key={i}>{s.field}: “{s.text}”</li>)}</ul>
                )}
              </details>
            )}

            {po.status && (
              <details open>
                <summary>Purchase order {po.po_ref ? `(${po.po_ref})` : '(proposed)'}</summary>
                {po.sandbox && <div style={{ color: '#b45309' }}>SANDBOX SUPPLIER — no real PO transmitted</div>}
                <div>Status <strong>{po.status}</strong> · qty {po.quantity}
                  {po.total_amount_cents != null && <> · wholesale total {po.total_amount_cents}c</>}</div>
              </details>
            )}

            <details open>
              <summary>Journey ({journey.length})</summary>
              <ol>
                {journey.map((e, i) => (
                  <li key={i}>
                    <code>{e.event}</code> → <strong>{e.state}</strong> by {e.actor_type}
                    {e.reason_code ? ` (${e.reason_code})` : ''} <small>{e.valid_from}</small>
                  </li>
                ))}
              </ol>
            </details>
          </section>
        )}
      </div>
    </div>
  );
}

export default ProcurementCases;
