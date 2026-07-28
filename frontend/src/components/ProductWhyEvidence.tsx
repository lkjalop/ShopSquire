export type ProductWhyExplanation = {
  sku?: string;
  reason_summary?: string;
  matched_constraints?: string[];
  rank_factors?: any[];
  disqualifiers?: string[];
  alternatives_not_selected?: any[];
};

export function hasRetainedRankingEvidence(explanation: ProductWhyExplanation): boolean {
  return Boolean(
    explanation.matched_constraints?.length
    || explanation.rank_factors?.length
    || explanation.alternatives_not_selected?.length,
  );
}

export default function ProductWhyEvidence({ explanation }: { explanation: ProductWhyExplanation }) {
  const hasEvidence = hasRetainedRankingEvidence(explanation);

  if (!hasEvidence) {
    return (
      <div role="status">
        <strong>Ranking evidence unavailable.</strong>{' '}
        This response did not retain matched constraints, rank factors, or considered alternatives, so this product
        should not be treated as a verified best fit.
        {explanation.disqualifiers?.length
          ? <div><strong>Recorded disqualifiers:</strong> {explanation.disqualifiers.join(', ')}</div>
          : null}
      </div>
    );
  }

  return (
    <>
      <div><strong>Matched constraints:</strong> {explanation.matched_constraints?.join(', ') || 'None returned'}</div>
      <div><strong>Rank factors:</strong> {explanation.rank_factors?.length || 0}</div>
      <div><strong>Disqualifiers:</strong> {explanation.disqualifiers?.join(', ') || 'None returned'}</div>
      <div><strong>Alternatives not selected:</strong> {explanation.alternatives_not_selected?.length || 0}</div>
      {explanation.reason_summary
        ? <div><strong>Summary:</strong> {explanation.reason_summary}</div>
        : <div><strong>Summary:</strong> Not returned</div>}
    </>
  );
}

