/** SupplierDraftPacket — the supplier-email approval packet: recipient/scope/gate cards, the evidence
 *  packet, and the editable draft with a pending-diff warning (extracted from ProcurementCases).
 *  Presentational; the save-edit action is the parent's callback. */
import React from 'react';

const shortHash = (v?: any) => String(v || '').slice(0, 8) || 'none';

export function SupplierDraftPacket({
  draft, state, recipientDisplay, draftEvidence, draftChanged,
  editSubject, setEditSubject, editBody, setEditBody, busy, onSaveEdit,
}: {
  draft: Record<string, any>;
  state: string;
  recipientDisplay: string;
  draftEvidence: any[];
  draftChanged: boolean;
  editSubject: string;
  setEditSubject: (v: string) => void;
  editBody: string;
  setEditBody: (v: string) => void;
  busy: boolean;
  onSaveEdit: () => void;
}) {
  if (!draft.subject) return null;
  return (
    <details open data-testid="op-supplier-draft">
      <summary>Supplier email approval packet - hash {shortHash(draft.content_hash)}</summary>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8, margin: '8px 0' }}>
        <div style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 8, background: '#fff' }}>
          <strong>Recipient</strong>
          <div data-testid="op-draft-recipient">{recipientDisplay}</div>
          <small style={{ color: '#6b7280' }}>
            Domain boundary: {draft.recipient_domain || 'unknown'}; source: approved supplier allowlist
          </small>
        </div>
        <div style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 8, background: '#fff' }}>
          <strong>Commercial scope</strong>
          <div>Item {draft.commercial_scope?.item_ref || 'unknown'} - qty {draft.commercial_scope?.quantity ?? 'unknown'}</div>
          <small style={{ color: '#6b7280' }}>No price or PO commitment is allowed in the draft body.</small>
        </div>
        <div style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 8, background: '#fff' }}>
          <strong>Approval gate</strong>
          <div data-testid="op-draft-gate">
            {state === 'AWAITING_APPROVAL' ? 'Human review pending' : state === 'APPROVED_TO_SEND' ? 'Approved to send' : 'Draft staged'}
          </div>
          <small style={{ color: draftChanged ? '#b45309' : '#6b7280' }}>
            {draftChanged ? 'Unsaved edit: save to create a new hash before send.' : `Pinned hash ${shortHash(draft.content_hash)}`}
          </small>
        </div>
      </div>

      {draftEvidence.length > 0 && (
        <div data-testid="op-draft-evidence" style={{ margin: '8px 0' }}>
          <strong>Evidence packet</strong>
          <ul style={{ marginTop: 4 }}>
            {draftEvidence.map((e: any, i: number) => (
              <li key={`${e.evidence_id || e.source || 'ev'}-${i}`}>
                <code>{e.evidence_id || e.source || `EV-${i + 1}`}</code>{' '}
                {e.source ? <span>{e.source}: </span> : null}
                {e.summary || e.provenance || 'evidence attached'}
              </li>
            ))}
          </ul>
        </div>
      )}

      {state === 'AWAITING_APPROVAL' ? (
        <div data-testid="op-edit-draft" style={{ display: 'grid', gap: 6, margin: '6px 0' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <strong>Editable draft</strong>
            {editSubject !== String(draft.subject || '') && <span style={{ color: '#b45309', fontSize: 12 }}>subject changed</span>}
            {editBody !== String(draft.body || '') && <span style={{ color: '#b45309', fontSize: 12 }}>body changed</span>}
          </div>
          <input value={editSubject} onChange={(e) => setEditSubject(e.target.value)}
                 data-testid="op-edit-subject" placeholder="Subject" />
          <textarea value={editBody} onChange={(e) => setEditBody(e.target.value)} rows={6}
                    data-testid="op-edit-body" placeholder="Body" />
          {draftChanged && (
            <div data-testid="op-edit-diff" style={{ padding: 8, border: '1px solid #f59e0b', borderRadius: 8, background: '#fffbeb' }}>
              <strong>Pending diff:</strong>{' '}
              {editSubject !== String(draft.subject || '') ? 'subject ' : ''}
              {editBody !== String(draft.body || '') ? 'body ' : ''}
              changed. Save edit before requesting or sending approval.
            </div>
          )}
          <div>
            <button disabled={busy || !draftChanged} data-testid="op-edit-save" onClick={onSaveEdit}>
              Save edit (re-hash → re-approve)
            </button>
            <small style={{ marginLeft: 8, color: '#6b7280' }}>
              editing voids the prior approval; price/PO leaks are rejected
            </small>
          </div>
        </div>
      ) : (
        <>
          <div><strong>Subject:</strong> <span data-testid="op-draft-subject">{draft.subject}</span></div>
          <pre data-testid="op-draft-body" style={{ whiteSpace: 'pre-wrap', border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 10 }}>{draft.body}</pre>
        </>
      )}
      {Array.isArray(draft.rationale) && (
        <ul>{draft.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
      )}
    </details>
  );
}

export default SupplierDraftPacket;
