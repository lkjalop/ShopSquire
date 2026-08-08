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
  authority_status: 'unverified' | string;
};

type Props = {
  claims: BuyerRequirementClaim[];
  onAccept?: (acceptedClaimIds: string[], researchChoice: 'local_only' | 'research_and_corroborate') => Promise<void>;
};

const label = (value: string) => value.replaceAll('_', ' ');

export default function BuyerRequirementReviewCard({ claims, onAccept }: Props) {
  const [selected, setSelected] = React.useState(() => new Set(claims.map((claim) => claim.claim_id)));
  const [busy, setBusy] = React.useState(false);
  const [status, setStatus] = React.useState('');
  if (!Array.isArray(claims) || claims.length === 0) return null;
  const accept = async (choice: 'local_only' | 'research_and_corroborate') => {
    if (!onAccept || busy) return;
    setBusy(true);
    setStatus('');
    try {
      await onAccept([...selected], choice);
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
        These came from your upload. They are provisional and unverified; no product has
        been qualified and no cart action was authorized.
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
            {claim.operator} {Array.isArray(claim.value) ? claim.value.join(' or ') : String(claim.value)}
            {claim.unit ? ` ${claim.unit}` : ''}
            {' '}· {label(claim.requirement_class)} · {label(claim.constraint_tier)}
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 8, fontSize: 12 }}>
        Select the claims to use. Buyer acceptance keeps them provisional until corroborated.
      </div>
      {onAccept && (
        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <button type="button" disabled={busy || selected.size === 0} onClick={() => { void accept('local_only'); }}>
            Use provisionally
          </button>
          <button type="button" disabled={busy || selected.size === 0} onClick={() => { void accept('research_and_corroborate'); }}>
            Research and corroborate
          </button>
        </div>
      )}
      {status && <div role="status" style={{ marginTop: 8, fontSize: 12 }}>{status}</div>}
    </section>
  );
}
