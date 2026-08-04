import { describe, expect, it } from 'vitest';
import { dealEconomicsStatus, formatDealMoney } from '../dealEconomicsDisplay';

describe('deal economics display', () => {
  it('keeps estimated supplier economics visibly non-authoritative', () => {
    const view = dealEconomicsStatus({
      verdict: 'healthy',
      currency: 'AUD',
      max_discount_cents: 50_000,
      discount_authorized: false,
      cost_is_estimated: true,
      landed_cost_complete: false,
    });

    expect(view.verdict).toBe('HEALTHY');
    expect(view.estimated).toBe(true);
    expect(view.costLabel).toBe('Estimated supplier cost');
    expect(view.discountLabel).toContain('locked');
    expect(view.discountLabel).not.toContain('$500');
  });

  it('formats authorized landed-cost headroom in tenant currency', () => {
    const view = dealEconomicsStatus({
      currency: 'AUD',
      max_discount_cents: 50_000,
      discount_authorized: true,
      landed_cost_complete: true,
    });

    expect(view.discountLabel).toContain('$500');
    expect(formatDealMoney(191_900, 'AUD')).toContain('$1,919');
  });
});
