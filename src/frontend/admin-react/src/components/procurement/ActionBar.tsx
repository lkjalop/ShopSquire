/** ActionBar — the state-driven procurement workflow buttons (extracted from ProcurementCases). Each
 *  button maps to ONE backend transition; the workflow enforces the actor + the two gates, so the bar
 *  only renders what the case's state permits. */
import React from 'react';
import {
  fcCompleteCase, fcDemoReply, fcDispatch, fcDraftQuote, fcExecutePO, fcGenerateOptions,
  fcProposePO, fcRequestApproval, fcValidateQuote,
} from '../../api';

const SCENARIOS = ['full_quote', 'partial_availability', 'late_delivery', 'substitute_offer',
  'expired_quote', 'untrusted_sender', 'contradictory_quantity'];

export function ActionBar({
  sel, state, busy, draftItemRef, draftQty, draftChanged, draftHash, scenario, setScenario, run, onEconomics,
}: {
  sel: string;
  state: string;
  busy: boolean;
  draftItemRef: string;
  draftQty: number;
  draftChanged: boolean;
  draftHash?: string;
  scenario: string;
  setScenario: (v: string) => void;
  run: (fn: () => Promise<any>) => Promise<void>;
  onEconomics: () => void;
}) {
  const draftDisabled = busy || !draftItemRef || draftQty <= 0;
  return (
    <div className="actions" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
      {state === 'COMMITTED' && (
        <>
          <button disabled={draftDisabled} data-testid="op-draft"
                  title={!draftItemRef || draftQty <= 0 ? 'Case is missing assessed item/shortfall evidence.' : `Draft for ${draftItemRef} x ${draftQty}`}
                  onClick={() => run(() => fcDraftQuote(sel, draftItemRef, draftQty))}>
            Draft quote (agent)
          </button>
          {(!draftItemRef || draftQty <= 0) && (
            <small style={{ color: '#b45309' }}>missing assessed item or shortfall; re-run availability assessment</small>
          )}
        </>
      )}
      {state === 'QUOTE_DRAFTED' && (
        <button disabled={busy} data-testid="op-request-approval"
                onClick={() => run(() => fcRequestApproval(sel))}>Request approval</button>
      )}
      {(state === 'AWAITING_APPROVAL' || state === 'APPROVED_TO_SEND') && (
        <button disabled={busy || !draftHash || draftChanged} data-testid="op-dispatch"
                title={draftChanged ? 'Save the edited draft before approval/send.' : 'Approve and send this exact content hash.'}
                onClick={() => run(() => fcDispatch(sel, draftHash || ''))}>
          Approve exact draft &amp; send (GATE 2)
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
        <button disabled={busy} data-testid="op-economics" onClick={onEconomics}>Deal economics</button>
      )}
    </div>
  );
}

export default ActionBar;
