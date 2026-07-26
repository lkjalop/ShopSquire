import { describe, expect, it } from 'vitest';

import { normalizePendingBulkBudget } from '../bulkBudget';

describe('normalizePendingBulkBudget', () => {
  it('preserves total scope supplied by confirmed slots', () => {
    expect(normalizePendingBulkBudget(
      {
        quantity: 50,
        total_cents: 10_000_000,
        per_unit_cents: 200_000,
        units_affordable: 28,
      },
      {
        budget_scope: 'total',
        total_budget_cents: 10_000_000,
      },
    )).toMatchObject({
      quantity: 50,
      total_cents: 10_000_000,
      units_affordable: 28,
      scope: 'total',
    });
  });

  it('prefers an explicit budget scope and rejects non-object payloads', () => {
    expect(normalizePendingBulkBudget(
      { total_cents: 100_000, budget_scope: 'per_unit' },
      { budget_scope: 'total' },
    )).toMatchObject({ scope: 'per_unit' });
    expect(normalizePendingBulkBudget([], {})).toBeNull();
  });
});
