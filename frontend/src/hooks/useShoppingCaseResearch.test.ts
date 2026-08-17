import { describe, expect, it } from 'vitest';
import {
  initialShoppingCasePresentationState,
  shoppingCasePresentationReducer,
} from './useShoppingCaseResearch';

describe('shoppingCasePresentationReducer', () => {
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
