import styles from './ProductWhyEvidence.module.css';

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
  material_unknowns?: Array<string | { label?: string; question?: string; unknown_id?: string }>;
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
    requirement_class?: string;
    verification_status?: string;
    scope_caveat?: string;
    artefact_name?: string;
    artefact_version?: string;
    freshness_status?: string;
    decision_verdict?: string;
  }>;
  decision_narration?: string;
  workload_decision?: {
    schema_version?: string;
    overall_decision?: string;
    compatibility_status?: string;
    performance_status?: string;
    scale_status?: string;
    qualification_scope?: string;
    workload?: {
      desired_outcome?: string;
      artefact_name?: string;
      artefact_version?: string;
      material_unknowns?: string[];
    };
    product?: {
      identifier_type?: string;
      identifier?: string;
      form_factor?: string;
      configuration_hash?: string;
    };
    fit_ledger?: Array<{
      attribute_key: string;
      attribute_label?: string;
      required_text?: string;
      observed_text?: string;
      verdict?: string;
      requirement_class?: string;
      verification_status?: string;
      scope_caveat?: string;
      requirement_claim_ids?: string[];
      capability_claim_ids?: string[];
    }>;
    infrastructure_alternatives?: {
      alternatives?: Array<{
        architecture_class: string;
        label: string;
        execution_location?: string;
        mobility?: string;
        tradeoffs_to_verify?: string[];
      }>;
    };
    critic?: { status?: string; violations?: string[] };
  };
};

const readable = (value?: string) => String(value || 'unknown').replaceAll('_', ' ');

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
  const decision = explanation.workload_decision;
  const decisionRows = decision?.fit_ledger || [];

  if (!hasEvidence && !hasFitEvidence && !decision) {
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
      {decision && (
        <section className={styles.decision} aria-label="Workload decision">
          <div className={styles.header}>
            <div>
              <div className={styles.eyebrow}>Fit for your stated scope</div>
              <strong className={styles.verdict}>{readable(decision.overall_decision)}</strong>
              <div className={styles.scope}>
                {decision.workload?.desired_outcome || explanation.workload_summary || 'Buyer requirements'}
                {decision.workload?.artefact_name
                  ? ` · ${decision.workload.artefact_name}${decision.workload.artefact_version ? ` ${decision.workload.artefact_version}` : ''}`
                  : ' · artefact unresolved'}
              </div>
            </div>
            <div className={styles.statusGrid} aria-label="Decision status summary">
              <span>Compatibility <b>{readable(decision.compatibility_status)}</b></span>
              <span>Performance <b>{readable(decision.performance_status)}</b></span>
              <span>Scale <b>{readable(decision.scale_status)}</b></span>
            </div>
          </div>

          {explanation.decision_narration ? <p className={styles.narration}>{explanation.decision_narration}</p> : null}

          <div className={styles.ledger} role="table" aria-label="Fit receipt">
            {decisionRows.map((row) => (
              <div className={styles.row} role="row" key={row.attribute_key}>
                <div role="cell"><strong>{row.attribute_label || readable(row.attribute_key)}</strong><small>{readable(row.requirement_class)}</small></div>
                <div role="cell"><small>Required</small>{row.required_text || 'not recorded'}</div>
                <div role="cell"><small>Observed</small>{row.observed_text || 'not recorded'}</div>
                <div role="cell" className={styles[row.verdict || 'unknown'] || styles.unknown}>
                  {readable(row.verdict)}
                </div>
                {row.scope_caveat ? <div className={styles.caveat} role="note">{row.scope_caveat}</div> : null}
              </div>
            ))}
          </div>

          {decision.workload?.material_unknowns?.length ? (
            <div className={styles.unknownPanel} role="note">
              <strong>Still needed before a stronger qualification</strong>
              <ul>{decision.workload.material_unknowns.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}

          <details className={styles.alternatives}>
            <summary>Compare where this workload should run</summary>
            <div className={styles.alternativeGrid}>
              {decision.infrastructure_alternatives?.alternatives?.map((item) => (
                <article key={item.architecture_class}>
                  <strong>{item.label}</strong>
                  <small>{readable(item.execution_location)} · {readable(item.mobility)}</small>
                  <span>{item.tradeoffs_to_verify?.slice(0, 2).join(' · ')}</span>
                </article>
              ))}
            </div>
            <div role="note">No architecture is selected automatically.</div>
          </details>

          <details className={styles.audit}>
            <summary>Evidence and critic</summary>
            <div>Product identity: {decision.product?.identifier || 'unresolved'} ({readable(decision.product?.identifier_type)})</div>
            <div>Form factor: {readable(decision.product?.form_factor)}</div>
            <div>Critic: {readable(decision.critic?.status)}</div>
            {decision.critic?.violations?.length ? <div>Blocked by: {decision.critic.violations.join(', ')}</div> : null}
          </details>
        </section>
      )}
      {!decision && hasFitEvidence && (
        <section aria-label="Product workload fit">
          <div><strong>Workload:</strong> {explanation.workload_summary || 'Buyer requirements'}</div>
          <div><strong>Overall fit:</strong> {explanation.coverage_status?.replaceAll('_', ' ') || 'not assessed'}</div>
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
          {explanation.material_unknowns?.length ? (
            <div role="note">
              <strong>Still needed before claiming full suitability:</strong>{' '}
              {explanation.material_unknowns.map((item) => (
                typeof item === 'string'
                  ? item
                  : item.label || item.question || item.unknown_id || 'unresolved requirement'
              )).join(', ')}
            </div>
          ) : null}
          <div role="note">
            Laptop, workstation/server, hybrid, and cloud execution can require different capabilities.
            Unknown deployment or compatibility facts must be resolved before treating this as a complete workflow fit.
          </div>
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
