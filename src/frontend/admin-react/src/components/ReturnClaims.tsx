import React, { useCallback, useEffect, useState } from 'react';
import {
  downloadAuthenticated,
  fetchReturnClaim,
  fetchReturnClaims,
  setReturnEvidenceLegalHold,
  transitionReturnClaim,
  type ReturnClaim,
} from '../api';

const NEXT_STATES = [
  'needs_info', 'under_review', 'approved', 'repair_authorized', 'in_transit',
  'received_at_facility', 'repair_in_progress', 'repaired', 'replacement_sent',
  'refund_pending', 'refunded', 'rejected', 'closed',
];

export function ReturnClaims({ role }: { role: string }) {
  const [claims, setClaims] = useState<ReturnClaim[]>([]);
  const [selected, setSelected] = useState<ReturnClaim | null>(null);
  const [nextState, setNextState] = useState('under_review');
  const [reason, setReason] = useState('Operator reviewed the available evidence');
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const result = await fetchReturnClaims();
      setClaims(result.claims);
      if (selected) setSelected(await fetchReturnClaim(selected.claim_id));
      setError('');
    } catch (exc: any) {
      setError(exc?.message || 'Return queue unavailable');
    }
  }, [selected?.claim_id]);

  useEffect(() => { refresh(); }, []);

  const open = async (claimId: string) => {
    try { setSelected(await fetchReturnClaim(claimId)); setError(''); }
    catch (exc: any) { setError(exc?.message || 'Return claim unavailable'); }
  };

  const transition = async () => {
    if (!selected) return;
    try {
      await transitionReturnClaim(selected.claim_id, nextState, reason);
      setSelected(await fetchReturnClaim(selected.claim_id));
      await refresh();
    } catch (exc: any) { setError(exc?.message || 'Transition failed'); }
  };

  const setHold = async (evidenceId: string, enabled: boolean) => {
    if (!selected) return;
    try {
      await setReturnEvidenceLegalHold(
        selected.claim_id, evidenceId, enabled,
        enabled ? 'Preserve evidence for active investigation' : 'Investigation hold released',
      );
      setSelected(await fetchReturnClaim(selected.claim_id));
    } catch (exc: any) { setError(exc?.message || 'Legal hold update failed'); }
  };

  const download = async (evidenceId: string) => {
    if (!selected) return;
    try {
      const blob = await downloadAuthenticated(
        `/api/v1/returns/claims/${encodeURIComponent(selected.claim_id)}/evidence/` +
        `${encodeURIComponent(evidenceId)}/content?purpose=${encodeURIComponent('Operator evidence investigation')}`,
      );
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = href; anchor.download = `return-evidence-${evidenceId}.bin`; anchor.click();
      URL.revokeObjectURL(href);
    } catch (exc: any) { setError(exc?.message || 'Evidence access failed'); }
  };

  return (
    <div className="return-claims" data-testid="return-claims-console">
      {error && <p role="alert">{error}</p>}
      <div className="return-claims-grid">
        <section>
          <div className="panel-title-row"><h3>Return and repair queue</h3><button onClick={refresh}>Refresh</button></div>
          {claims.length === 0 && <p>No return claims in this tenant.</p>}
          {claims.map((claim) => (
            <button className="return-claim-row" key={claim.claim_id} onClick={() => open(claim.claim_id)}>
              <strong>{claim.sku}</strong><span>{claim.status.replace(/_/g, ' ')}</span>
              <small>{claim.order_verification_status} · {claim.abuse_status}</small>
            </button>
          ))}
        </section>
        <section>
          {!selected && <p>Select a claim to inspect its governed lifecycle.</p>}
          {selected && <>
            <h3>{selected.sku} · {selected.status.replace(/_/g, ' ')}</h3>
            <div className="return-trust-strip">
              <span>Order: {selected.order_verification_status}</span>
              <span>Abuse control: {selected.abuse_status}</span>
              <span>Security: {selected.evidence_job?.security_status || 'pending'}</span>
              <span>Authority: operator governed</span>
            </div>
            {selected.abuse_reasons?.length > 0 && (
              <p className="warning">Review signals: {selected.abuse_reasons.join(', ')}. This is not a fraud finding.</p>
            )}
            <h4>Encrypted evidence custody</h4>
            {selected.evidence?.map((evidence) => (
              <div className="return-evidence-row" key={evidence.evidence_id}>
                <div><strong>{evidence.filename}</strong><small>{evidence.cipher} · key {evidence.encryption_key_id}</small></div>
                <span>{evidence.legal_hold ? 'LEGAL HOLD' : `retain to ${evidence.retention_until.slice(0, 10)}`}</span>
                {role === 'owner' && <>
                  <button onClick={() => setHold(evidence.evidence_id, !evidence.legal_hold)}>
                    {evidence.legal_hold ? 'Release hold' : 'Place hold'}
                  </button>
                  <button onClick={() => download(evidence.evidence_id)}>Audited access</button>
                </>}
              </div>
            ))}
            <h4>Lifecycle</h4>
            <ol>{selected.timeline?.map((event) => <li key={event.sequence}>{event.event_type}: {event.to_status}</li>)}</ol>
            <div className="return-transition-controls">
              <select value={nextState} onChange={(event) => setNextState(event.target.value)}>
                {NEXT_STATES.map((state) => <option key={state} value={state}>{state.replace(/_/g, ' ')}</option>)}
              </select>
              <input aria-label="Transition reason" value={reason} onChange={(event) => setReason(event.target.value)} />
              <button onClick={transition}>Apply governed transition</button>
            </div>
          </>}
        </section>
      </div>
    </div>
  );
}
