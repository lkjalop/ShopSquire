export type BuyerClaimReconciliation = {
  buyer_claim_id: string;
  attribute: string;
  status: 'corroborated' | 'contradicted' | 'unresolved' | 'preference_only';
  official_claim_ids?: string[];
  reason: string;
};

const colour = {
  corroborated: '#166534', contradicted: '#991b1b',
  unresolved: '#92400e', preference_only: '#475569',
};

export default function BuyerClaimReconciliationCard({ rows }: {
  rows: BuyerClaimReconciliation[];
}) {
  if (!Array.isArray(rows) || rows.length === 0) return null;
  return (
    <section
      data-testid="buyer-claim-reconciliation"
      aria-label="Uploaded requirement corroboration"
      style={{ marginTop: 8, border: '1px solid #cbd5e1', borderRadius: 8, padding: 9, background: '#fff' }}
    >
      <strong>What approved-source research established</strong>
      <div style={{ marginTop: 3, fontSize: 12 }}>
        Buyer-supplied constraints remain distinguishable from independently corroborated claims.
      </div>
      <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
        {rows.map((row) => (
          <li key={row.buyer_claim_id} style={{ marginTop: 4, fontSize: 12 }}>
            <strong>{row.attribute.replaceAll('_', ' ')}</strong>:{' '}
            <span style={{ color: colour[row.status], fontWeight: 700 }}>
              {row.status.replaceAll('_', ' ')}
            </span>
            {' — '}{row.reason}
          </li>
        ))}
      </ul>
    </section>
  );
}
