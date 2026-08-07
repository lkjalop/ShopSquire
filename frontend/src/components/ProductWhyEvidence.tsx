export type ProductWhyExplanation = {
  sku?: string;
  reason_summary?: string;
  matched_constraints?: string[];
  rank_factors?: any[];
  disqualifiers?: string[];
  alternatives_not_selected?: any[];
  workload_summary?: string;
  qualification_scope?: string;
  coverage_status?: string;
  fit_ledger?: Array<{
    attribute: string;
    attribute_label?: string;
    required: any[];
    required_text?: string;
    observed?: any;
    observed_text?: string;
    verdict: string;
    requirement_source?: string;
    requirement_evidence_refs?: string[];
  }>;
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
  const hasFitEvidence = Boolean(explanation.fit_ledger?.length);

  if (!hasEvidence && !hasFitEvidence) {
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
      {hasFitEvidence && (
        <section aria-label="Product workload fit">
          <div><strong>Workload:</strong> {explanation.workload_summary || 'Buyer requirements'}</div>
          <div><strong>Coverage:</strong> {explanation.coverage_status || 'not assessed'}</div>
          {explanation.fit_ledger!.map((row) => (
            <div key={row.attribute}>
              <strong>{row.attribute_label || row.attribute.replaceAll('_', ' ')}:</strong>{' '}
              {row.observed_text ?? String(row.observed ?? 'unknown')} against{' '}
              {row.required_text ?? JSON.stringify(row.required)} ({row.verdict})
            </div>
          ))}
          {explanation.coverage_status === 'partial' && (
            <div role="note">Partial qualification: untested workflow dimensions remain unknown.</div>
          )}
        </section>
      )}
      {hasEvidence && (
        <>
          <div><strong>Matched constraints:</strong> {explanation.matched_constraints?.join(', ') || 'None returned'}</div>
          <div><strong>Rank factors:</strong> {explanation.rank_factors?.length || 0}</div>
          <div><strong>Disqualifiers:</strong> {explanation.disqualifiers?.join(', ') || 'None returned'}</div>
          <div><strong>Alternatives not selected:</strong> {explanation.alternatives_not_selected?.length || 0}</div>
        </>
      )}
      {explanation.reason_summary
        ? <div><strong>Summary:</strong> {explanation.reason_summary}</div>
        : <div><strong>Summary:</strong> Not returned</div>}
    </>
  );
}
