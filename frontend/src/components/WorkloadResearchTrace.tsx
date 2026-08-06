type Props = {
  executionSteps?: any[];
};

const words = (value: unknown) => String(value || 'not recorded').replace(/_/g, ' ');

const RequirementRows = ({ title, value }: { title: string; value: any }) => {
  const rows = value && typeof value === 'object' ? Object.entries(value) : [];
  if (!rows.length) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <strong>{title}</strong>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 5 }}>
        {rows.map(([key, item]) => (
          <span key={key} style={{ padding: '4px 7px', background: '#f1f5f9', borderRadius: 4 }}>
            {words(key)}: <strong>{String(item)}</strong>
          </span>
        ))}
      </div>
    </div>
  );
};

export default function WorkloadResearchTrace({ executionSteps = [] }: Props) {
  const proposal = executionSteps.find((step) => step?.id === 'model-proposal') || {};
  const evidence = executionSteps.find((step) => step?.id === 'workload-evidence') || {};
  const authorization = executionSteps.find((step) => step?.id === 'workload-authorization') || {};
  const researchPlan = executionSteps.find((step) => step?.id === 'research-plan') || {};
  const semanticEvidence = executionSteps.find((step) => step?.id === 'semantic-evidence') || {};
  const semanticAuthorization = executionSteps.find((step) => step?.id === 'semantic-authorization') || {};
  const evidenceOutput = evidence?.output || {};
  const evidenceItems = Array.isArray(evidenceOutput.items) ? evidenceOutput.items : [];
  const entities = Array.isArray(proposal?.output?.workload_entities)
    ? proposal.output.workload_entities : [];
  const planOutput = researchPlan?.output || {};
  const evidenceNeeds = Array.isArray(planOutput?.evidence_needs) ? planOutput.evidence_needs : [];
  const materialSlots = Array.isArray(planOutput?.material_slots) ? planOutput.material_slots : [];
  const semanticLegs = semanticEvidence?.output?.legs || {};
  const hasResearch = Boolean(
    evidence.id || authorization.id || entities.length || researchPlan.id
    || semanticEvidence.id || semanticAuthorization.id
  );

  if (!hasResearch) {
    return <div style={{ color: '#64748b' }}>No named-workload research was required for this turn.</div>;
  }

  return (
    <section data-testid="workload-research-trace">
      <h3 style={{ margin: '0 0 10px', fontSize: 16 }}>Research and product-fit authorization</h3>
      <div style={{ display: 'grid', gap: 8 }}>
        <div style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
          <strong>1. Model interpretation</strong>
          <div data-testid="research-model-entities" style={{ marginTop: 5 }}>
            {entities.length
              ? entities.map((item: any) => `${words(item?.kind)}: ${item?.name || 'unnamed'}`).join(' | ')
              : (Array.isArray(planOutput?.subject_spans) && planOutput.subject_spans.length
                ? planOutput.subject_spans.join(' | ')
                : 'No bounded workload entity was proposed.')}
          </div>
          <small style={{ color: '#64748b' }}>The model proposes identity and evidence needs; it does not authorize product fit.</small>
        </div>

        {researchPlan.id && (
          <div style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>2. Bounded research plan</strong>
            <div style={{ marginTop: 5 }}>
              External research authorized: <strong>{planOutput?.external_research_authorized ? 'yes' : 'no'}</strong>
            </div>
            <div>Interpretation source: <strong>{words(planOutput?.interpretation_origin)}</strong></div>
            <div>
              Research status: <strong>{words(researchPlan?.status || 'not recorded')}</strong>
            </div>
            <div>Provider fan-out limit: <strong>{planOutput?.max_provider_fanout || 'not recorded'}</strong></div>
            <div>Turn deadline: <strong>{planOutput?.total_timeout_ms ? `${planOutput.total_timeout_ms}ms` : 'not recorded'}</strong></div>
            {evidenceNeeds.length > 0 && (
              <ul data-testid="research-evidence-needs" style={{ margin: '6px 0 0', paddingLeft: 20 }}>
                {evidenceNeeds.map((need: any, index: number) => (
                  <li key={need?.need_id || index}>
                    {words(need?.claim_type)} for {need?.subject_span || 'unrecorded subject'} via {words(need?.provider_capability)}
                  </li>
                ))}
              </ul>
            )}
            {materialSlots.length > 0 && (
              <div style={{ marginTop: 6 }}>Remaining material slots: {materialSlots.map((slot: any) => slot?.question).filter(Boolean).join(' | ')}</div>
            )}
          </div>
        )}

        <div style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
          <strong>{researchPlan.id ? '3' : '2'}. Governed provider search</strong>
          <div style={{ marginTop: 5 }}>
            Buyer consent recorded: <strong>{evidenceOutput.consent_recorded ? 'yes' : 'no'}</strong>
          </div>
          {evidenceItems.length ? evidenceItems.map((item: any, index: number) => {
            const attempts = Array.isArray(item?.provider_attempts) ? item.provider_attempts : [];
            return (
              <div key={`${item?.kind || 'workload'}-${item?.requested_name || index}`} style={{ marginTop: 9, paddingTop: 8, borderTop: '1px solid #e2e8f0' }}>
                <div><strong>{item?.requested_name || 'Unnamed workload'}</strong> - {words(item?.status)}</div>
                <div>Provider coverage: <strong>{words(item?.provider_coverage)}</strong></div>
                <div>Live provider access for this workload: <strong>{item?.live_allowed ? 'yes' : 'no'}</strong></div>
                {attempts.length ? (
                  <ul style={{ margin: '5px 0 0', paddingLeft: 20 }}>
                    {attempts.map((attempt: any, attemptIndex: number) => (
                      <li key={`${attempt?.provider_id || 'provider'}-${attemptIndex}`}>
                        {attempt?.provider_id || 'unknown provider'}: {words(attempt?.status)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div data-testid="research-no-provider" style={{ color: '#b45309', marginTop: 4 }}>
                    No enrolled provider supports this workload kind. No external requirement claim was accepted.
                  </div>
                )}
                {item?.source_url && (
                  <div style={{ marginTop: 4 }}>
                    Source: <a href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a>
                    {' '}({item?.retrieved_at || 'retrieval time not recorded'})
                  </div>
                )}
                <RequirementRows title="Minimum evidence" value={item?.minimum} />
                <RequirementRows title="Recommended evidence" value={item?.recommended} />
                <RequirementRows title="Requested target" value={item?.requested_target} />
              </div>
            );
          }) : (
            <div style={{ marginTop: 5, color: '#b45309' }}>
              {researchPlan.id && !planOutput?.external_research_authorized
                ? 'Not attempted - buyer consent is required before external research.'
                : 'No provider result was recorded.'}
            </div>
          )}
          {semanticEvidence.id && Object.entries(semanticLegs).map(([name, leg]: [string, any]) => (
            <div key={name} style={{ marginTop: 8, paddingTop: 7, borderTop: '1px solid #e2e8f0' }}>
              <strong>{words(name)}</strong>: {words(leg?.data?.status || (leg?.found ? 'accepted candidate' : 'attempted empty'))}
              {leg?.summary && <div style={{ marginTop: 3 }}>{leg.summary}</div>}
            </div>
          ))}
        </div>

        <div style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
          <strong>{researchPlan.id ? '4' : '3'}. Deterministic authorization</strong>
          <div style={{ marginTop: 5 }}>
            Status: <strong>{words(semanticAuthorization?.status || authorization?.status || 'not run')}</strong>
          </div>
          <div>Reason: {words(semanticAuthorization?.output?.reasons?.[0] || authorization?.output?.reason)}</div>
          <div>
            Prevented: {Array.isArray((semanticAuthorization?.output || authorization?.output)?.state_prevented)
              ? (semanticAuthorization?.output || authorization?.output).state_prevented.map(words).join(' | ')
              : 'none recorded'}
          </div>
          <small style={{ color: '#64748b' }}>
            This is an auditable decision record, not private model chain-of-thought.
          </small>
        </div>
      </div>
    </section>
  );
}
