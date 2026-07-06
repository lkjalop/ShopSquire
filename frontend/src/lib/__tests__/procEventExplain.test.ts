import { describe, it, expect } from 'vitest';
import { explainProcEvent } from '../procEventExplain';

describe('explainProcEvent', () => {
  it('explains availability with a shortfall and its consequence', () => {
    const e = explainProcEvent('bulk_availability_assessed', { sku: 'LAP-1', order_qty: 30, in_stock: 15, shortfall: 15 })!;
    expect(e.what).toContain('15 in stock against 30 requested');
    expect(e.why).toContain('routes to supplier sourcing');
  });

  it('explains a fully-in-stock line without inventing sourcing', () => {
    const e = explainProcEvent('bulk_availability_assessed', { sku: 'LAP-1', order_qty: 10, in_stock: 40, shortfall: 0 })!;
    expect(e.why).toContain('no supplier sourcing');
  });

  it('explains market intelligence from recorded recommendation + rationale only', () => {
    const e = explainProcEvent('market_intelligence_assessed',
      { signal_count: 4, recommendation: 'review pricing before promoting', rationale: 'competitor below list' })!;
    expect(e.what).toContain('4 active market signal(s)');
    expect(e.what).toContain('review pricing');
    expect(e.why).toBe('competitor below list');
  });

  it('is honest when there are no signals', () => {
    const e = explainProcEvent('market_intelligence_assessed', { signal_count: 0 })!;
    expect(e.what).toContain('internal-only');
  });

  it('explains supplier selection + channel with the recorded rationale', () => {
    expect(explainProcEvent('supplier_selected', { supplier_ref: 'SUP-BIZ', item_ref: 'LAP-1', quantity: 15 })!.what)
      .toContain('SUP-BIZ');
    const ch = explainProcEvent('supplier_channel_resolved', { channel: 'phone', rationale: 'human calls' })!;
    expect(ch.what).toContain('PHONE');
    expect(ch.why).toBe('human calls');
  });

  it('returns null for unknown event types (drill-down falls back to JSON only)', () => {
    expect(explainProcEvent('mystery_event', {})).toBeNull();
  });
});
