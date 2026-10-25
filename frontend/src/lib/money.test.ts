import { describe, expect, it } from 'vitest';

import { formatProductPrice } from './money';

describe('formatProductPrice', () => {
  it.each(['AUD', 'USD', 'EUR'])('preserves listed cents for %s prices', currency => {
    expect(formatProductPrice({price_cents:6995,currency})).toContain('69.95');
    expect(formatProductPrice({price:69.95,currency})).toContain('69.95');
  });
  it('uses the product currency instead of assuming USD', () => {
    expect(formatProductPrice({ price: 2899, currency: 'AUD' })).toContain('AUD');
  });

  it('supports cents and does not invent a zero price', () => {
    expect(formatProductPrice({ price_cents: 159900, currency: 'AUD' })).toContain('1,599');
    expect(formatProductPrice({ currency: 'AUD' })).toBe('\u2014');
  });
});
