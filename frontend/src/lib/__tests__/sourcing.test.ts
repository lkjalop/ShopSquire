import { describe, it, expect } from 'vitest';
import {
  sourcedCasesFrom,
  sourcedCaseCountFrom,
  sourcingIntentAfterSelection,
} from '../sourcing';

describe('sourcingIntentAfterSelection', () => {
  const intent = {
    mode: 'deferred_to_cart',
    pr_id: 'pr-stable',
    planned_case_count: 1,
    requirements: { use_case: 'game_development' },
    unresolved_phrases: [{ phrase: 'unknown dock', quantity: 1 }],
    lines: [{ item_ref: 'LAP-MSI', name: 'MSI laptop', quantity: 20, shortfall: 5 }],
  };

  it('keeps a preview whose product matches the selected cart SKU', () => {
    expect(sourcingIntentAfterSelection(intent, 'LAP-MSI')).toBe(intent);
  });

  it('invalidates stale product lines but preserves sourcing context for cart confirmation', () => {
    expect(sourcingIntentAfterSelection(intent, 'LAP-ASUS')).toEqual({
      mode: 'deferred_to_cart',
      pr_id: 'pr-stable',
      requirements: { use_case: 'game_development' },
      unresolved_phrases: [],
      lines: [],
      planned_case_count: undefined,
    });
  });
});

describe('sourcedCasesFrom / sourcedCaseCountFrom', () => {
  it('reads top-level cases on a first confirm', () => {
    const res = { order_group_id: 'g1', case_count: 2, cases: [{ case_id: 'A' }, { case_id: 'B' }] };
    expect(sourcedCasesFrom(res).map((c) => c.case_id)).toEqual(['A', 'B']);
    expect(sourcedCaseCountFrom(res)).toBe(2);
  });

  it('reads the NESTED created.cases after a supersede (the amend path)', () => {
    // buyer amended the order → old cases retired, NEW cases live under `created`. Reading top-level
    // `cases` here (which the backend does NOT populate on supersede) would commit nothing → the demo bug.
    const res = {
      order_group_id: 'g1', status: 'superseded' as const, superseded: ['STALE'],
      created: { case_count: 1, cases: [{ case_id: 'NEW' }] },
    };
    expect(sourcedCasesFrom(res).map((c) => c.case_id)).toEqual(['NEW']);
    expect(sourcedCaseCountFrom(res)).toBe(1);
  });

  it('prefers created over top-level when both are present', () => {
    const res = {
      order_group_id: 'g1', case_count: 5, cases: [{ case_id: 'STALE' }],
      created: { case_count: 1, cases: [{ case_id: 'NEW' }] },
    };
    expect(sourcedCasesFrom(res).map((c) => c.case_id)).toEqual(['NEW']);
    expect(sourcedCaseCountFrom(res)).toBe(1);
  });

  it('is safe on null / empty / missing shapes', () => {
    expect(sourcedCasesFrom(null)).toEqual([]);
    expect(sourcedCasesFrom(undefined)).toEqual([]);
    expect(sourcedCasesFrom({ order_group_id: null })).toEqual([]);
    expect(sourcedCaseCountFrom(null)).toBe(0);
    expect(sourcedCaseCountFrom({ order_group_id: null })).toBe(0);
    // created present but null (operator_required path returns created: null)
    expect(sourcedCaseCountFrom({ order_group_id: 'g', created: null, case_count: 3 })).toBe(3);
  });
});
