type Props = {
  executionSteps?: any[];
  events?: any[];
};

const words = (value: unknown) => String(value || 'not recorded').replace(/[_-]+/g, ' ');

const isOfficialResearchEvent = (event: any) => {
  const payload = event?.payload || {};
  if (Array.isArray(payload.evidence_ladder) && payload.evidence_ladder.length > 0) return true;
  return [event?.event_type, payload?._original_event_type, payload?._event_type].some((value) => {
    const eventType = String(value || '').toLowerCase();
    return eventType.includes('official_research_rerank_completed')
      || eventType.includes('buyer_evidence_source_researched')
      || eventType.includes('open_world_discovery_completed');
  });
};

const isAmbiguityExplorationEvent = (event: any) => (
  [event?.event_type, event?.payload?._original_event_type, event?.payload?._event_type]
    .some((value) => String(value || '').toLowerCase() === 'ambiguity_exploration_projected')
);

const isShoppingCaseObligationEvent = (event: any) => (
  [event?.event_type, event?.payload?._original_event_type, event?.payload?._event_type]
    .some((value) => String(value || '').toLowerCase() === 'shopping_case_obligations_retained')
);

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

export default function WorkloadResearchTrace({ executionSteps = [], events = [] }: Props) {
  const proposal = executionSteps.find((step) => step?.id === 'model-proposal') || {};
  const evidence = executionSteps.find((step) => step?.id === 'workload-evidence') || {};
  const authorization = executionSteps.find((step) => step?.id === 'workload-authorization') || {};
  const researchPlan = executionSteps.find((step) => step?.id === 'research-plan') || {};
  const researchTrigger = executionSteps.find((step) => step?.id === 'research-trigger-observer') || {};
  const postCatalogTrigger = executionSteps.find(
    (step) => step?.id === 'research-trigger-post-catalog-observer',
  ) || {};
  const buyerConsent = executionSteps.find((step) => step?.id === 'buyer-research-consent') || {};
  const compiler = executionSteps.find(
    (step) => step?.id === 'semantic-requirements-compiler' || step?.id === 'requirements-compiler',
  ) || {};
  const semanticEvidence = executionSteps.find((step) => step?.id === 'semantic-evidence') || {};
  const semanticAuthorization = executionSteps.find((step) => step?.id === 'semantic-authorization') || {};
  const materialClarification = executionSteps.find((step) => step?.id === 'material-clarification') || {};
  const commercialCase = executionSteps.find((step) => step?.id === 'commercial-case-reducer') || {};
  const officialResearch = [...events].reverse().find(isOfficialResearchEvent)?.payload || {};
  const provisionalExploration = [...events].reverse().find(isAmbiguityExplorationEvent)?.payload || {};
  const retainedObligations = events
    .filter(isShoppingCaseObligationEvent)
    .flatMap((event) => Array.isArray(event?.payload?.obligations) ? event.payload.obligations : []);
  const evidenceLadder = Array.isArray(officialResearch?.evidence_ladder)
    ? officialResearch.evidence_ladder : [];
  const evidenceOutput = evidence?.output || {};
  const evidenceItems = Array.isArray(evidenceOutput.items) ? evidenceOutput.items : [];
  const entities = Array.isArray(proposal?.output?.workload_entities)
    ? proposal.output.workload_entities : [];
  const planOutput = researchPlan?.output || {};
  const evidenceNeeds = Array.isArray(planOutput?.evidence_needs) ? planOutput.evidence_needs : [];
  const materialSlots = Array.isArray(planOutput?.material_slots) ? planOutput.material_slots : [];
  const queryBundle = Array.isArray(planOutput?.query_bundle) ? planOutput.query_bundle : [];
  const semanticLegs = semanticEvidence?.output?.legs || {};
  const providerUsage = semanticEvidence?.output?.provider_usage || {};
  const effort = semanticEvidence?.output?.effort || {};
  const hypotheses = Array.isArray(semanticAuthorization?.output?.workload_hypotheses)
    ? semanticAuthorization.output.workload_hypotheses : [];
  const unknowns = Array.isArray(semanticAuthorization?.output?.material_unknowns)
    ? semanticAuthorization.output.material_unknowns : [];
  const compiledRequirements = Array.isArray(compiler?.output?.compiled_requirements)
    ? compiler.output.compiled_requirements : [];
  const rejectedClaims = Array.isArray(compiler?.output?.rejected_claims)
    ? compiler.output.rejected_claims : [];
  const consentRecorded = Object.keys(officialResearch).length > 0 || (evidence.id
    ? Boolean(evidenceOutput.consent_recorded)
    : buyerConsent?.status === 'recorded');
  const hasResearch = Boolean(
    evidence.id || authorization.id || entities.length || researchPlan.id || researchTrigger.id
    || postCatalogTrigger.id
    || semanticEvidence.id || semanticAuthorization.id || evidenceLadder.length
    || provisionalExploration?.research_plan_id
  );

  if (!hasResearch) {
    return (
      <div style={{ color: '#64748b' }}>
        No governed workload research record was produced. This does not establish that research was unnecessary.
      </div>
    );
  }

  return (
    <section data-testid="workload-research-trace">
      <h3 style={{ margin: '0 0 10px', fontSize: 16 }}>Research and product-fit authorization</h3>
      <div style={{ display: 'grid', gap: 8 }}>
        {provisionalExploration?.research_plan_id && (
          <div data-testid="provisional-research-plan" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Bounded research plan</strong>
            <div style={{ marginTop: 5 }}>
              Purpose: <strong>{provisionalExploration.retained_purpose || 'not recorded'}</strong>
            </div>
            <div>
              Status: <strong>not executed</strong> - provisional catalog exploration is allowed while material evidence gaps remain visible.
            </div>
            <div>Plan: <strong>{provisionalExploration.research_plan_id}</strong></div>
            {Array.isArray(provisionalExploration.interpretations) && provisionalExploration.interpretations.length > 0 && (
              <div style={{ marginTop: 7 }}>
                <strong>Bounded interpretations</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                  {provisionalExploration.interpretations.map((item: any, index: number) => (
                    <li key={item?.hypothesis_id || index}>
                      {item?.label || item?.description || words(item?.hypothesis_id)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {Array.isArray(provisionalExploration.research_obligations) && provisionalExploration.research_obligations.length > 0 && (
              <div style={{ marginTop: 7 }}>
                <strong>Open resolution obligations</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                  {provisionalExploration.research_obligations.map((item: any, index: number) => (
                    <li key={item?.obligation_id || index}>
                      {words(item?.obligation_type || item?.kind || item?.ambiguity_type || 'research obligation')}
                      {item?.description ? `: ${item.description}` : ''}
                      {item?.resolution_owner ? ` - owner: ${words(item.resolution_owner)}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div data-testid="provisional-provider-accounting" style={{ marginTop: 7, color: '#475569' }}>
              Execution: {words(provisionalExploration.execution)}
              {' · '}Evidence: {words(provisionalExploration.evidence)}
              {' · '}Decision: {words(provisionalExploration.decision)}
              {' · '}External calls: {String(provisionalExploration?.provider_accounting?.external_calls ?? 0)}
              {' · '}Paid calls: {String(provisionalExploration?.provider_accounting?.paid_calls ?? 0)}
              {' · '}Cart authority: {words(provisionalExploration.cart_authority)}
            </div>
            <small style={{ color: '#64748b' }}>
              This records a case-bound plan and local exploration, not an external fetch or verified product fit.
            </small>
          </div>
        )}
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
          {hypotheses.length > 0 && (
            <div data-testid="research-hypotheses" style={{ marginTop: 7 }}>
              <strong>Competing hypotheses to investigate</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                {hypotheses.map((item: any, index: number) => (
                  <li key={item?.hypothesis_id || index}>
                    {item?.label || 'Unnamed hypothesis'} - proposed, not accepted
                    {item?.confidence != null ? ` (${Math.round(Number(item.confidence) * 100)}% interpreter confidence)` : ''}
                    {item?.evidence_coverage ? `; evidence coverage: ${words(item.evidence_coverage)}` : ''}
                    {Array.isArray(item?.matched_claim_types) && item.matched_claim_types.length
                      ? ` (${item.matched_claim_types.map(words).join(', ')})` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {unknowns.length > 0 && (
            <div data-testid="research-material-unknowns" style={{ marginTop: 7 }}>
              <strong>Material unknowns</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                {unknowns.map((item: any, index: number) => (
                  <li key={item?.unknown_id || index}>
                    {item?.description || words(item?.unknown_id)} - resolved by {words(item?.resolution_source)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {evidenceLadder.length > 0 && (
          <div data-testid="governed-evidence-ladder" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Governed evidence ladder</strong>
            <div style={{ marginTop: 5, color: '#475569' }}>
              Each rung reports execution truth. An infrastructure failure is not an evidence conclusion.
            </div>
            <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
              {evidenceLadder.map((tier: any) => (
                <div key={`${tier.tier}-${tier.mechanism}`} style={{ borderTop: '1px solid #e2e8f0', paddingTop: 6 }}>
                  <strong>Tier {tier.tier}: {words(tier.mechanism)}</strong>
                  {' — '}{words(tier.execution_status)}
                  {tier.rejection_reason ? ` (${words(tier.rejection_reason)})` : ''}
                  <div style={{ fontSize: 12, color: '#475569' }}>
                    Billing: {words(tier.billing_class)}
                    {tier.dispatch_count != null ? ` · dispatched: ${tier.dispatch_count}` : ''}
                    {tier.allowlisted_result_count != null
                      ? ` · allowlisted hits: ${tier.allowlisted_result_count}` : ''}
                  </div>
                  {Array.isArray(tier.engines_queried) && tier.engines_queried.length > 0 && (
                    <div style={{ fontSize: 12 }}>
                      Queried: {tier.engines_queried.join(', ')}
                      {' · '}Responded: {(tier.engines_responded || []).join(', ') || 'none'}
                    </div>
                  )}
                  {Array.isArray(tier.engine_failures) && tier.engine_failures.length > 0 && (
                    <ul style={{ margin: '3px 0 0', paddingLeft: 20, color: '#b45309' }}>
                      {tier.engine_failures.map((failure: any, index: number) => (
                        <li key={`${failure.engine || 'engine'}-${index}`}>
                          {failure.engine || 'unknown engine'}: {failure.reason || 'unresponsive'}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            <small style={{ color: '#64748b' }}>
              Missing evidence remains not verified. No unavailable source establishes safety, compatibility, or fit.
            </small>
          </div>
        )}

        {Object.keys(officialResearch).length > 0 && (
          <div data-testid="official-research-outcome" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Approved-source research outcome</strong>
            <div style={{ marginTop: 5 }}>
              Status: <strong>{words(officialResearch.status || 'completed')}</strong>
              {' · '}Evidence: <strong>{words(officialResearch.evidence_outcome)}</strong>
            </div>
            <div>
              External provider calls: <strong>{String(officialResearch?.provider_accounting?.external_calls ?? 0)}</strong>
              {' · '}Official fetches: <strong>{String(officialResearch?.provider_accounting?.official_origin_fetches ?? 0)}</strong>
              {' · '}Cache hits: <strong>{String(officialResearch?.provider_accounting?.cache_hits ?? 0)}</strong>
              {' · '}Paid calls: <strong>{String(officialResearch?.provider_accounting?.paid_calls ?? 0)}</strong>
            </div>
            <small style={{ color: '#64748b' }}>
              Cart authority: {words(officialResearch.cart_authority)}. Supplier authority: {words(officialResearch.supplier_authority)}.
            </small>
          </div>
        )}

        {retainedObligations.length > 0 && (
          <div data-testid="shopping-case-retained-obligations" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Case-bound follow-up obligations</strong>
            <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
              {retainedObligations.map((item: any, index: number) => (
                <li key={`${item?.kind || 'obligation'}-${index}`}>
                  {words(item?.obligation_type || item?.kind)} - owner: {words(item?.resolution_owner)}
                  {item?.buyer_text ? `; buyer said: ${item.buyer_text}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        {researchTrigger.id && (
          <div data-testid="research-trigger-observer" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Adaptive research assessment - shadow only</strong>
            <div style={{ marginTop: 5 }}>State: <strong>{words(researchTrigger?.output?.state)}</strong></div>
            <div>Recommendation: <strong>{words(researchTrigger?.output?.recommendation)}</strong></div>
            <div>Score: <strong>{researchTrigger?.output?.score ?? 'not recorded'}</strong></div>
            <div>Reasons: <strong>{(researchTrigger?.output?.reasons || []).map(words).join(' | ') || 'none recorded'}</strong></div>
            <small style={{ color: '#64748b' }}>
              Uncalibrated observer. It cannot authorize research, requirements, products, or actions.
            </small>
          </div>
        )}

        {postCatalogTrigger.id && (
          <div data-testid="research-trigger-post-catalog-observer" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Post-catalog research assessment - shadow only</strong>
            <div style={{ marginTop: 5 }}>Qualified products: <strong>{postCatalogTrigger?.output?.features?.qualified_product_count ?? 'not recorded'}</strong></div>
            <div>Catalog coverage gap: <strong>{postCatalogTrigger?.output?.features?.catalog_coverage_gap ?? 'not recorded'}</strong></div>
            <div>Unknown attribute ratio: <strong>{postCatalogTrigger?.output?.features?.unknown_attribute_ratio ?? 'not recorded'}</strong></div>
            <small style={{ color: '#64748b' }}>Observed after retrieval; it cannot authorize research, products, or actions.</small>
          </div>
        )}

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
            {queryBundle.length > 0 && (
              <div data-testid="research-query-bundle" style={{ marginTop: 7 }}>
                <strong>Planned query bundle</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                  {queryBundle.map((item: any, index: number) => (
                    <li key={item?.query_id || index}>
                      {words(item?.strategy)}: {item?.text || 'query text not recorded'}
                      {' '}<em>(planned only; no authority)</em>
                      {Array.isArray(item?.prohibited_assumptions) && item.prohibited_assumptions.length
                        ? `; prohibited: ${item.prohibited_assumptions.map(words).join(', ')}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {materialSlots.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <div>Material slots:</div>
                <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                  {materialSlots.map((slot: any, index: number) => (
                    <li key={slot?.slot_id || index}>
                      {slot?.question || words(slot?.slot_id)} - <strong>{words(slot?.answer_status || 'unresolved')}</strong>
                      {slot?.answer_candidate ? `: ${slot.answer_candidate}` : ''}
                      {slot?.answer_status === 'candidate' ? ' (buyer-authored; awaiting authoritative evidence)' : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
          <strong>{researchPlan.id ? '3' : '2'}. Governed provider search</strong>
          <div style={{ marginTop: 5 }}>
            Buyer consent recorded: <strong>{consentRecorded ? 'yes' : 'no'}</strong>
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
                        {words(attempt?.provider_id || 'unknown provider')}: {words(attempt?.status)}
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
              <strong>{words(name)}</strong>: {words(
                leg?.data?.status
                || (leg?.execution_status === 'rejected_admission' ? 'not started - internal effort admission rejected'
                  : leg?.health === 'timed_out' ? 'provider timeout'
                  : leg?.health === 'cancelled' ? 'research pending'
                    : leg?.health === 'failed' || leg?.health === 'degraded'
                      ? 'research degraded'
                      : (leg?.found ? 'accepted candidate' : 'no authoritative evidence')),
              )}
              {leg?.error && (
                <div style={{ marginTop: 3, color: '#b45309' }}>
                  {leg?.execution_status === 'rejected_admission' ? 'Internal scheduler status' : 'Provider status'}:
                  {' '}{words(leg.error)}
                </div>
              )}
              {leg?.summary && <div style={{ marginTop: 3 }}>{leg.summary}</div>}
              {Array.isArray(leg?.data?.provider_attempts) && leg.data.provider_attempts.length > 0 && (
                <ul data-testid="semantic-provider-attempts" style={{ margin: '5px 0 0', paddingLeft: 20 }}>
                  {leg.data.provider_attempts.map((attempt: any, index: number) => (
                    <li key={`${attempt?.provider_id || 'unconfigured'}-${attempt?.capability || index}-${index}`}>
                      {words(attempt?.provider_id || 'No configured provider')}: {words(attempt?.status)}
                      {attempt?.capability ? ` for ${words(attempt.capability)}` : ''}
                      {attempt?.deadline_ms ? ` (${attempt.deadline_ms}ms deadline)` : ''}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {semanticEvidence.id && (
            <div data-testid="research-provider-usage" style={{ marginTop: 8, paddingTop: 7, borderTop: '1px solid #e2e8f0' }}>
              External provider calls: <strong>{String(providerUsage?.external_provider_call_count ?? 0)}</strong>
              {' · '}Paid calls: <strong>{providerUsage?.paid_provider_call_count_status === 'recorded'
                ? String(providerUsage?.paid_provider_call_count ?? 0) : 'not recorded'}</strong>
              {' · '}Internal effort: <strong>{String(effort?.used_effort_units ?? 0)} / {String(effort?.max_effort_units ?? 'not recorded')}</strong>
            </div>
          )}
        </div>

        {materialClarification.id && (
          <div data-testid="material-clarification-trace" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Material clarification decision</strong>
            <div style={{ marginTop: 5 }}>{materialClarification?.output?.question || 'Question not recorded'}</div>
            <div>Buyer-owned gap: <strong>{(materialClarification?.output?.missing_slots || []).map(words).join(' | ') || 'not recorded'}</strong></div>
            <div>Expected impact: <strong>{(materialClarification?.output?.decision_impacts || []).map(words).join(' | ') || 'not recorded'}</strong></div>
            <div>Selection policy: <strong>{words(materialClarification?.output?.selection_policy)}</strong></div>
            {materialClarification?.output?.bounded_value_score != null && (
              <div>
                Bounded value score: <strong>{String(materialClarification.output.bounded_value_score)}</strong>
                {' '}({words(materialClarification?.output?.selection_calibration || 'unsealed')})
              </div>
            )}
            {materialClarification?.output?.hypotheses_discriminated != null && (
              <div>Hypotheses distinguished: <strong>{String(materialClarification.output.hypotheses_discriminated)}</strong></div>
            )}
            <small style={{ color: '#64748b' }}>
              One material question is selected after bounded research. The answer does not itself authorize a product or action.
            </small>
          </div>
        )}

        {compiler.id && (
          <div style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Evidence-to-requirement compilation</strong>
            <div style={{ marginTop: 5 }}>Status: <strong>{words(compiler.status)}</strong></div>
            {compiledRequirements.length > 0 && (
              <ul data-testid="compiled-requirements" style={{ margin: '6px 0 0', paddingLeft: 20 }}>
                {compiledRequirements.map((item: any, index: number) => (
                  <li key={`${item?.attribute_key || 'requirement'}-${index}`}>
                    {words(item?.attribute_key)} {item?.operator} {String(item?.value)} {item?.unit || ''}
                  </li>
                ))}
              </ul>
            )}
            {rejectedClaims.length > 0 && (
              <div style={{ marginTop: 5, color: '#b45309' }}>
                Rejected evidence: {rejectedClaims.map((item: any) => words(item?.reason)).join(' | ')}
              </div>
            )}
            <small style={{ color: '#64748b' }}>
              Accepted official evidence may establish fit predicates; it never authorizes cart, RFQ, or payment actions.
            </small>
          </div>
        )}

        {commercialCase.id && (
          <div data-testid="commercial-case-trace" style={{ border: '1px solid #cbd5e1', padding: 10, borderRadius: 6 }}>
            <strong>Commercial feasibility and amendments</strong>
            <div style={{ marginTop: 5 }}>Status: <strong>{words(commercialCase.status)}</strong></div>
            {(commercialCase?.output?.obligations || []).map((item: any, index: number) => (
              <div key={`${item?.kind || 'obligation'}-${index}`} style={{ marginTop: 5 }}>
                {words(item?.kind)}: {item?.field_name || 'action'}
                {item?.proposed_value != null ? ` → ${String(item.proposed_value)}` : ''}
                {' '}({words(item?.status)})
              </div>
            ))}
            {(() => {
              const pending = (commercialCase?.output?.obligations || []).find(
                (item: any) => item?.proposed_value != null && item?.authorization_granted !== true,
              );
              return pending ? (
                <div style={{ marginTop: 5 }}>
                  Proposed value: <strong>{String(pending.proposed_value)}</strong>. This change requires buyer confirmation.
                </div>
              ) : null;
            })()}
            <div>Prior quantity: <strong>{commercialCase?.output?.prior_quantity ?? 'not recorded'}</strong></div>
            <small style={{ color: '#64748b' }}>
              Arithmetic and case consistency are deterministic. A pending amendment does not mutate the cart or authorize an order.
            </small>
          </div>
        )}

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
