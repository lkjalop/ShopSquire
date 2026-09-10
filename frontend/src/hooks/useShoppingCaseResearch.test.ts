import { describe, expect, it } from 'vitest';
import {
  initialShoppingCasePresentationState,
  shoppingCasePresentationReducer,
} from './useShoppingCaseResearch';

describe('shoppingCasePresentationReducer', () => {
  it('installs the new case and clears old evidence/shelves in one transition', () => {
    const prior = { ...initialShoppingCasePresentationState,
      activeShoppingCase: { case_id: 'old', retained_purpose: 'old workload' },
      ambiguityExploration: { case_id: 'old' } as any,
      productShelves: { schema_version: 'product-shelves-v1', shelves: [] } as any,
      supplierContinuation: { caseId: 'old' } as any,
    };
    const next = shoppingCasePresentationReducer(prior, { type: 'terminal.installed',
      value: { activeShoppingCase: { case_id: 'new', retained_purpose: 'new purchase', revision: 2 },
        ambiguityExploration: null, productShelves: null, supplierContinuation: null } });
    expect(next.activeShoppingCase?.case_id).toBe('new');
    expect(next.ambiguityExploration).toBeNull();
    expect(next.productShelves).toBeNull();
    expect(next.supplierContinuation).toBeNull();
  });
  it('projects case state through one reducer without losing sibling projections', () => {
    const withCase = shoppingCasePresentationReducer(initialShoppingCasePresentationState, {
      type: 'active.replaced',
      value: { case_id: 'sc-1', retained_purpose: 'rendering' },
    });
    const withAmbiguity = shoppingCasePresentationReducer(withCase, {
      type: 'ambiguity.replaced',
      value: { case_id: 'sc-1', retained_purpose: 'rendering' } as any,
    });
    const patched = shoppingCasePresentationReducer(withAmbiguity, {
      type: 'ambiguity.replaced',
      value: (current) => current ? { ...current, status: 'researched' } : current,
    });

    expect(patched.activeShoppingCase?.case_id).toBe('sc-1');
    expect(patched.ambiguityExploration?.status).toBe('researched');
  });

  it('clears all case-bound projections atomically', () => {
    const populated = {
      ...initialShoppingCasePresentationState,
      activeShoppingCase: { case_id: 'sc-1', retained_purpose: 'rendering' },
      productShelves: { schema_version: 'product-shelves-v1', shelves: [] } as any,
      supplierContinuation: { caseId: 'sc-1' } as any,
    };
    expect(shoppingCasePresentationReducer(populated, { type: 'case.cleared' }))
      .toEqual(initialShoppingCasePresentationState);
  });
});
