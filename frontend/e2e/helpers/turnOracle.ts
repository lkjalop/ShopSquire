/** Test oracle only. Expectations come from the test scenario, not the model. */
export function turnViolations(response: any, expected: {
  budgetMax?: number; role?: string; acceptedClaims?: number;
  qualifiedDelivery?: boolean;
} = {}): string[] {
  const failures: string[] = [];
  const terminal = response.terminal_outcome;
  if (!terminal) return ['terminal_missing'];
  const read = response.turn_read_model;
  for (const key of ['operation_id', 'case_revision']) {
    if (!terminal[key] || read?.[key] !== terminal[key]) failures.push(`identity:${key}`);
  }
  const facts = terminal.canonical_facts || {};
  if (expected.budgetMax !== undefined && facts.canonical_budget?.budget_max !== expected.budgetMax)
    failures.push('budget:buyer_fact');
  if (JSON.stringify(terminal.right_panel?.canonical_budget) !== JSON.stringify(facts.canonical_budget))
    failures.push('budget:panel');
  if (expected.role !== undefined && facts.subject_role !== expected.role) failures.push('subject:role');
  const research = terminal.research_outcome;
  if (expected.acceptedClaims !== undefined && research?.accepted_claim_count !== expected.acceptedClaims)
    failures.push('evidence:acceptance');
  const cards = (terminal.product_shelves?.shelves || []).flatMap((s: any) =>
    [...(s.initial || []), ...(s.remaining || []), ...(s.next_page || [])]);
  const qualified = cards.filter((c: any) => c.fit_status === 'qualified');
  if (research?.catalog_authority === 'blocked' && qualified.length) failures.push('authority:stale_shelf');
  if (expected.qualifiedDelivery && !qualified.length) failures.push('delivery:empty');
  if (research?.requirement_completeness === 'complete' && research?.accepted_claim_count > 0 &&
      (terminal.next_questions || []).some((q: any) => q.goal === 'resolve_named_workload'))
    failures.push('questions:obsolete_requirements');
  if (terminal.commerce_authority !== 'none') failures.push('commerce:authority');
  return failures;
}
