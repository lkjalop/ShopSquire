import React from 'react';

export type BuyerRequirementClaim = {
  claim_id: string;
  attribute: string;
  operator: string;
  value: number | string | string[];
  unit?: string | null;
  requirement_class: string;
  constraint_tier: string;
  source_excerpt?: string;
  condition?: string | null;
  authority_status: 'unverified' | 'case_origin_critic_accepted' | string;
};

type Props = {
  claims: BuyerRequirementClaim[];
  onAccept?: (
    acceptedClaimIds: string[],
    researchChoice: 'local_only' | 'research_and_corroborate',
    corrections: Record<string, unknown>[],
  ) => Promise<void>;
};

const label = (value: string) => value.replaceAll('_', ' ');

export default function BuyerRequirementReviewCard({ claims, onAccept }: Props) {
  const caseOriginEvidence = claims.some(
    (claim) => claim.authority_status === 'case_origin_critic_accepted',
  );
  const [selected, setSelected] = React.useState(() => new Set(claims.map((claim) => claim.claim_id)));
  const [draftValues, setDraftValues] = React.useState<Record<string, string>>(() => Object.fromEntries(
    claims.map((claim) => [
      claim.claim_id,
      Array.isArray(claim.value) ? claim.value.join(', ') : String(claim.value),
    ]),
  ));
  const [busy, setBusy] = React.useState(false);
  const [completed, setCompleted] = React.useState(false);
  const [status, setStatus] = React.useState('');
  if (!Array.isArray(claims) || claims.length === 0) return null;
  const accept = async (choice: 'local_only' | 'research_and_corroborate') => {
    if (!onAccept || busy) return;
    setBusy(true);
    setStatus('');
    try {
      const corrections = claims.flatMap((claim) => {
        if (!selected.has(claim.claim_id)) return [];
        const original = Array.isArray(claim.value) ? claim.value.join(', ') : String(claim.value);
        const draft = String(draftValues[claim.claim_id] ?? original).trim();
        if (draft === original) return [];
        const value = Array.isArray(claim.value)
          ? draft.split(',').map((item) => item.trim()).filter(Boolean)
          : typeof claim.value === 'number' ? Number(draft) : draft;
        if ((typeof value === 'number' && !Number.isFinite(value)) || value === '') return [];
        return [{
          claim_id: claim.claim_id, attribute: claim.attribute,
          operator: claim.operator, value, unit: claim.unit || null,
          requirement_class: claim.requirement_class,
          constraint_tier: claim.constraint_tier,
          condition: claim.condition || null,
        }];
      });
      await onAccept([...selected], choice, corrections);
      setCompleted(true);
      setStatus(choice === 'local_only' ? 'Accepted for provisional browsing.' : 'Accepted; approved-source research requested.');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Could not accept these requirements.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      aria-label="Review extracted requirements"
      data-testid="buyer-requirement-review"
      style={{
        marginTop: 10,
        border: '1px solid #f59e0b',
        borderRadius: 10,
        padding: 10,
        background: '#fffbeb',
        color: '#78350f',
      }}
    >
      <strong>Review extracted requirements</strong>
      <div style={{ marginTop: 4, fontSize: 12 }}>
        {caseOriginEvidence
          ? 'These cited claims came from the exact publisher origin you approved for this case. Review, correct, or reject them before they affect product fit. No cart action was authorized.'
          : 'These came from your upload. They are provisional and unverified; no product has been qualified and no cart action was authorized.'}
      </div>
      <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
        {claims.slice(0, 12).map((claim) => (
          <li key={claim.claim_id} style={{ marginTop: 3, listStyle: 'none' }}>
            <input
              type="checkbox"
              checked={selected.has(claim.claim_id)}
              aria-label={`Use ${label(claim.attribute)} requirement`}
              onChange={(event) => setSelected((current) => {
                const next = new Set(current);
                if (event.target.checked) next.add(claim.claim_id); else next.delete(claim.claim_id);
                return next;
              })}
            />{' '}
            <strong>{label(claim.attribute)}</strong>{' '}
            {claim.operator}{' '}
            <input
              aria-label={`Correct ${label(claim.attribute)} value`}
              value={draftValues[claim.claim_id] ?? ''}
              onChange={(event) => setDraftValues((current) => ({
                ...current, [claim.claim_id]: event.target.value,
              }))}
              style={{ width: Array.isArray(claim.value) ? 180 : 78 }}
            />
            {claim.unit ? ` ${claim.unit}` : ''}
            {' '}· {label(claim.requirement_class)} · {label(claim.constraint_tier)}
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 8, fontSize: 12 }}>
        {caseOriginEvidence
          ? 'Unedited cited claims retain case-only evidence authority. Edited claims become provisional buyer evidence.'
          : 'Select the claims to use. Buyer acceptance keeps them provisional until corroborated.'}
      </div>
      {onAccept && (
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <button type="button" disabled={busy || completed || selected.size === 0} onClick={() => { void accept('local_only'); }}>
            {caseOriginEvidence ? 'Accept case evidence' : 'Use provisionally'}
          </button>
          {!caseOriginEvidence && (
            <button type="button" disabled={busy || completed || selected.size === 0} onClick={() => { void accept('research_and_corroborate'); }}>
              Research and corroborate
            </button>
          )}
        </div>
      )}
      {status && <div role="status" style={{ marginTop: 8, fontSize: 12 }}>{status}</div>}
    </section>
  );
}
