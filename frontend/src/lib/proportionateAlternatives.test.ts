import { describe, expect, it } from 'vitest';

import type { ShelfProduct } from '../components/ProductShelvesPanel';
import { selectProportionateAlternatives } from './proportionateAlternatives';

const product = (sku: string, price: number, overrides: Partial<ShelfProduct> = {}): ShelfProduct => ({
  identity_key: `pc-${sku}`, title: sku, price_cents: price, currency: 'AUD',
  fit_status: 'conditional', relevance_score: 0.7,
  product: { sku, form_factor: 'laptop' }, unknowns: ['warranty'], ...overrides,
});

describe('selectProportionateAlternatives', () => {
  it('keeps only same-form-factor products saving at least 20% with no hard miss', () => {
    const preferred = product('P', 1_000_000, { relevance_score: 1 });
    const selected = selectProportionateAlternatives(preferred, [
      product('TOO-CLOSE', 850_000),
      product('GOOD', 800_000, { relevance_score: 0.9 }),
      product('HARD-MISS', 600_000, { misses: ['RAM'] }),
      product('DESKTOP', 500_000, { product: { sku: 'DESKTOP', form_factor: 'fixed_workstation' } }),
    ]);
    expect(selected.map((row) => row.sku)).toEqual(['GOOD']);
    expect(selected[0]).toMatchObject({ savingsCents: 200_000, savingsPercent: 20 });
  });

  it('returns at most three in deterministic fit-first order', () => {
    const preferred = product('P', 1_000_000);
    const selected = selectProportionateAlternatives(preferred, [
      product('A', 500_000, { relevance_score: 0.7 }),
      product('B', 700_000, { relevance_score: 0.9 }),
      product('C', 600_000, { relevance_score: 0.8 }),
      product('D', 400_000, { relevance_score: 0.6 }),
    ]);
    expect(selected.map((row) => row.sku)).toEqual(['B', 'C', 'A']);
  });

  it('does not compare prices across currencies without an FX authority', () => {
    const preferred = product('P', 1_000_000);
    expect(selectProportionateAlternatives(preferred, [
      product('USD', 100_000, { currency: 'USD' }),
    ])).toEqual([]);
  });
});
