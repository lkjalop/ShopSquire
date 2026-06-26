/**
 * FulfilmentOptions — the buyer side of an auditable procurement case.
 *
 * Renders the buyer-SAFE projection of a fulfilment_case (the server redacts supplier-private data):
 *   • AWAITING_BUYER_COMMITMENT → GATE 1: the buyer confirms sourcing (no supplier is contacted until
 *     this). Honest copy: nothing ordered, no delivery promised yet.
 *   • OPTIONS_READY            → the buyer picks ship-together / split / substitute, each with its
 *     tradeoffs and which hard constraints it satisfies (estimate vs confirmed clearly distinguished).
 *   • SELECTED / later          → confirmation that the choice is recorded + a human PO approval follows.
 *
 * It only POSTs commands (commit, select-option) and re-reads the case — the backend state machine is
 * the source of truth, so each button maps to exactly one tested transition.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  commitFulfillmentCase,
  getFulfillmentCase,
  selectFulfillmentOption,
  type FulfillmentOption,
} from '../lib/api';
import FulfilmentJourney from './FulfilmentJourney';

export interface FulfilmentCaseSummary {
  case_id: string;
  status?: string;
  shortfall?: number;
  item_ref?: string;
}

interface Props {
  caseSummary: FulfilmentCaseSummary;
  uid: string;
  pollMs?: number;
}

interface CaseView {
  state: string;
  state_json: { options?: FulfillmentOption[]; selection?: { option_id: string }; availability?: any };
}

export default function FulfilmentOptions({ caseSummary, uid, pollMs = 0 }: Props) {
  const caseId = caseSummary.case_id;
  const [view, setView] = useState<CaseView | null>(null);
  const [chosen, setChosen] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>('');
  const [showJourney, setShowJourney] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const v = await getFulfillmentCase(caseId, 'buyer');
      setView({ state: v.state, state_json: v.state_json || {} });
      setError('');
    } catch (e: any) {
      setError(e?.message || 'could not load case');
    }
  }, [caseId]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!pollMs) return;
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [pollMs, refresh]);

  const state = view?.state || caseSummary.status || 'NEW';
  const options = view?.state_json?.options || [];
  const selectedId = view?.state_json?.selection?.option_id;

  const onCommit = async () => {
    setBusy(true);
    try { await commitFulfillmentCase(caseId, uid); await refresh(); }
    catch (e: any) { setError(e?.message || 'commit failed'); }
    finally { setBusy(false); }
  };

  const onSelect = async () => {
    if (!chosen) return;
    setBusy(true);
    try { await selectFulfillmentOption(caseId, uid, chosen); await refresh(); }
    catch (e: any) { setError(e?.message || 'selection failed'); }
    finally { setBusy(false); }
  };

  return (
    <section data-testid="fulfilment-options" className="fulfilment-options" aria-label="Procurement">
      <header>
        <strong>Procurement</strong>{' '}
        <span data-testid="fc-status">{state.replace(/_/g, ' ').toLowerCase()}</span>
        <span className="fc-case-ref"> · {caseId.slice(0, 8)}</span>
        <button className="fc-journey-toggle" data-testid="fc-journey-toggle"
                onClick={() => setShowJourney((s) => !s)}>
          {showJourney ? 'Hide journey' : 'View journey'}
        </button>
      </header>

      {error && <p role="alert" data-testid="fc-error">{error}</p>}
      {showJourney && <FulfilmentJourney caseId={caseId} />}

      {state === 'AWAITING_BUYER_COMMITMENT' && (
        <div data-testid="fc-commit">
          <p>
            {caseSummary.shortfall ?? 0} unit(s) need sourcing from an approved supplier. We will only
            contact a supplier after you confirm — nothing is ordered and no delivery is promised yet.
          </p>
          <button disabled={busy} onClick={onCommit} data-testid="fc-commit-btn">
            Confirm sourcing
          </button>
        </div>
      )}

      {state === 'OPTIONS_READY' && options.length > 0 && (
        <div data-testid="fc-options">
          <p>Supplier availability confirmed. Choose fulfilment:</p>
          {options.map((o) => (
            <label key={o.option_id} className="fc-option" data-testid={`fc-option-${o.option_type}`}>
              <input type="radio" name="fc-option" value={o.option_id}
                     checked={chosen === o.option_id} onChange={() => setChosen(o.option_id)} />
              <span className="fc-option-title">{o.title}</span>
              {o.estimated_delivery_at && (
                <span className="fc-eta"> · est. delivery {o.estimated_delivery_at}</span>
              )}
              {!o.constraints_satisfied?.deadline_met && (
                <span className="fc-flag" data-testid="fc-flag-deadline"> · may miss deadline</span>
              )}
              {o.tradeoffs?.length > 0 && <em className="fc-tradeoffs"> — {o.tradeoffs.join('; ')}</em>}
            </label>
          ))}
          <button disabled={busy || !chosen} onClick={onSelect} data-testid="fc-select-btn">
            Confirm selection
          </button>
        </div>
      )}

      {(state === 'SELECTED' || state === 'PROCUREMENT_APPROVAL_REQUIRED') && (
        <p data-testid="fc-selected">
          Your choice is recorded{selectedId ? '' : ''}. A final purchase-order approval completes the order.
        </p>
      )}
    </section>
  );
}
