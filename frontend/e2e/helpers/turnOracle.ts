/** Test oracle only. Expectations come from the test scenario, not the model. */
export function turnViolations(response: any, expected: {
  budgetMax?: number; role?: string; acceptedClaims?: number;
  qualifiedDelivery?: boolean;
  buyerQuery?: string; taxonomyRoots?: string[]; forbiddenQuestionGoals?: string[];
} = {}): string[] {
  const failures: string[] = [];
  const terminal = response.terminal_outcome;
  if (!terminal) return ['terminal_missing'];
  const read = response.turn_read_model;
  for (const key of ['operation_id', 'case_revision']) {
    if (!terminal[key] || read?.[key] !== terminal[key]) failures.push(`identity:${key}`);
  }
  const facts = terminal.canonical_facts || {};
  if (expected.buyerQuery !== undefined && facts.buyer_query !== expected.buyerQuery)
    failures.push('subject:query');
  if (expected.taxonomyRoots !== undefined &&
      !expected.taxonomyRoots.includes(terminal.catalog_scope?.selected_taxonomy_root))
    failures.push('subject:purchase');
  if ((terminal.next_questions || []).some((q:any) => expected.forbiddenQuestionGoals?.includes(q.goal)))
    failures.push('questions:inapplicable');
  if (expected.budgetMax !== undefined && facts.canonical_budget?.budget_max !== expected.budgetMax)
    failures.push('budget:buyer_fact');
  if (JSON.stringify(terminal.right_panel?.canonical_budget) !== JSON.stringify(facts.canonical_budget))
    failures.push('budget:panel');
  if (expected.role !== undefined && facts.subject_role !== expected.role) failures.push('subject:role');
  const research = terminal.research_outcome;
  if (research?.case_revision != null && research.case_revision !== terminal.case_revision)
    failures.push('identity:research_revision');
  if (research?.case_id != null && terminal.case_id != null && research.case_id !== terminal.case_id)
    failures.push('identity:research_case');
  const steps = response.execution_steps || terminal.execution_evidence?.execution_steps || [];
  const degradedProposal = steps.some((s:any) => s.id === 'model-proposal' && s.status === 'degraded');
  if (degradedProposal && steps.some((s:any) => s.id === 'platform-authorization' &&
      s.status === 'accepted' && !s.input_provenance?.degraded)) failures.push('authority:lost_degradation');
  const policy = response.research_policy;
  if (policy && response.research_authorization_basis === 'tenant_policy' &&
      (!policy.external_research_enabled || !policy.auto_authorize_read_only))
    failures.push('policy:reported_effective_mismatch');
  if (expected.acceptedClaims !== undefined && research?.accepted_claim_count !== expected.acceptedClaims)
    failures.push('evidence:acceptance');
  const cards = terminal.product_shelves
    ? (terminal.product_shelves.shelves || []).flatMap((s: any) =>
      [...(s.initial || []), ...(s.remaining || []), ...(s.next_page || [])])
    : (terminal.products || []);
  const qualified = cards.filter((c: any) => c.fit_status === 'qualified');
  if ((terminal.catalog_authority === 'blocked' || research?.catalog_authority === 'blocked') && qualified.length)
    failures.push('authority:stale_shelf');
  if (expected.qualifiedDelivery && !qualified.length) failures.push('delivery:empty');
  if (research?.requirement_completeness === 'complete' && research?.accepted_claim_count > 0 &&
      (terminal.next_questions || []).some((q: any) => q.goal === 'resolve_named_workload'))
    failures.push('questions:obsolete_requirements');
  if (terminal.commerce_authority !== 'none') failures.push('commerce:authority');
  return failures;
}
