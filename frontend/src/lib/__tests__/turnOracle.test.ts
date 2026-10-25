import { describe, expect, it } from 'vitest';
import { turnViolations } from '../../../e2e/helpers/turnOracle';

function valid() {
  return { turn_read_model: {operation_id:'o', case_revision:2}, terminal_outcome: {
    operation_id:'o', case_revision:2, commerce_authority:'none',
    canonical_facts:{buyer_query:'a laptop', canonical_budget:{budget_max:3000}, subject_role:'RUN_SUBJECT_ON_PRODUCT'},
    catalog_scope:{selected_taxonomy_root:'el-6-6'},
    right_panel:{canonical_budget:{budget_max:3000}}, next_questions:[],
    research_outcome:{accepted_claim_count:6, requirement_completeness:'complete', catalog_authority:'permitted'},
    product_shelves:{shelves:[{initial:[{fit_status:'qualified', sku:'one'}]}]},
  }};
}
const expected = {buyerQuery:'a laptop', taxonomyRoots:['el-6-6'], forbiddenQuestionGoals:['gaming_gap'],
  budgetMax:3000, role:'RUN_SUBJECT_ON_PRODUCT', acceptedClaims:6, qualifiedDelivery:true};
describe('shared turn oracle rejects internally consistent but wrong outcomes', () => {
  it('checks qualified flat catalog products, not only grouped research shelves', () => {
    const response: any = valid();
    response.terminal_outcome.product_shelves = null;
    response.terminal_outcome.products = [{sku:'one', fit_status:'qualified'}];
    expect(turnViolations(response, expected)).toEqual([]);
    response.terminal_outcome.catalog_authority = 'blocked';
    expect(turnViolations(response, expected)).toContain('authority:stale_shelf');
  });
  it('does not substitute historical flat products for an explicitly empty shelf', () => {
    const response: any = valid();
    response.terminal_outcome.product_shelves.shelves = [];
    response.terminal_outcome.products = [{sku:'old', fit_status:'qualified'}];
    expect(turnViolations(response, expected)).toContain('delivery:empty');
  });
  it('accepts the independently expected outcome', () => expect(turnViolations(valid(), expected)).toEqual([]));
  it.each([
    ['identity:research_revision', (r:any) => { r.terminal_outcome.research_outcome.case_revision=1; }],
    ['authority:lost_degradation', (r:any) => { r.execution_steps=[
      {id:'model-proposal',status:'degraded'}, {id:'platform-authorization',status:'accepted'}]; }],
    ['policy:reported_effective_mismatch', (r:any) => { r.research_policy={external_research_enabled:true,auto_authorize_read_only:false}; r.research_authorization_basis='tenant_policy'; }],
    ['subject:purchase', (r:any) => { r.terminal_outcome.catalog_scope.selected_taxonomy_root='so-1'; }],
    ['subject:query', (r:any) => { r.terminal_outcome.canonical_facts.buyer_query='previous game'; }],
    ['questions:inapplicable', (r:any) => { r.terminal_outcome.next_questions=[{goal:'gaming_gap'}]; }],
    ['budget:buyer_fact', (r:any) => { r.terminal_outcome.canonical_facts.canonical_budget.budget_max=3600; r.terminal_outcome.right_panel.canonical_budget.budget_max=3600; }],
    ['subject:role', (r:any) => { r.terminal_outcome.canonical_facts.subject_role='PROCURE_SUBJECT'; }],
    ['identity:case_revision', (r:any) => { r.turn_read_model.case_revision=1; }],
    ['evidence:acceptance', (r:any) => { r.terminal_outcome.research_outcome.accepted_claim_count=9; }],
    ['authority:stale_shelf', (r:any) => { r.terminal_outcome.research_outcome.catalog_authority='blocked'; }],
    ['questions:obsolete_requirements', (r:any) => { r.terminal_outcome.next_questions=[{goal:'resolve_named_workload'}]; }],
    ['delivery:empty', (r:any) => { r.terminal_outcome.product_shelves.shelves=[]; }],
    ['commerce:authority', (r:any) => { r.terminal_outcome.commerce_authority='approved'; }],
  ] as const)('detects %s', (code, corrupt) => {
    const response=valid(); corrupt(response);
    expect(turnViolations(response, expected)).toContain(code);
  });
});
