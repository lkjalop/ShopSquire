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
  fcDemoReply, fcDispatch, fcDraftQuote, fcGenerateOptions, fcRequestApproval, fcValidateQuote,
  getFulfillmentCaseOp, getFulfillmentJourney, listFulfillmentCases,
  type FulfillmentCaseRow, type FulfillmentCaseView, type JourneyEvent,
} from '../api';

const SCENARIOS = ['full_quote', 'partial_availability', 'late_delivery', 'substitute_offer',
  'expired_quote', 'untrusted_sender', 'contradictory_quantity'];

export function ProcurementCases() {
  const [cases, setCases] = useState<FulfillmentCaseRow[]>([]);
  const [sel, setSel] = useState<string>('');
  const [view, setView] = useState<FulfillmentCaseView | null>(null);
  const [journey, setJourney] = useState<JourneyEvent[]>([]);
  const [scenario, setScenario] = useState('full_quote');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(() => {
    listFulfillmentCases().then(setCases).catch((e) => setError(e.message));
  }, []);
  const loadCase = useCallback((id: string) => {
    if (!id) return;
    Promise.all([getFulfillmentCaseOp(id), getFulfillmentJourney(id)])
      .then(([v, j]) => { setView(v); setJourney(j); setError(null); })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { if (sel) loadCase(sel); }, [sel, loadCase]);

  const draft = (view?.state_json?.draft || {}) as Record<string, any>;
  const parsed = (view?.state_json?.parsed_quote || view?.state_json?.validated_quote || {}) as Record<string, any>;
  const state = view?.state || '';

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
            <h3>{sel.slice(0, 8)} — <span data-testid="op-state">{state}</span></h3>
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
            </div>

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
                <summary>Parsed quote (confidence {parsed.confidence})</summary>
                <div>Qty {parsed.quoted_quantity} · unit {parsed.unit_amount_cents} · dispatch {parsed.dispatch_ready_at} · expires {parsed.quote_expires_at}</div>
                {parsed.contradictory && <div style={{ color: 'orange' }}>⚠ contradictory quantity — review</div>}
                {Array.isArray(parsed.evidence_spans) && (
                  <ul>{parsed.evidence_spans.map((s: any, i: number) => <li key={i}>{s.field}: “{s.text}”</li>)}</ul>
                )}
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
