import { describe, expect, it } from 'vitest';
import { procurementDraftPending, procurementGateDisplay } from '../procurementGateDisplay';

describe('procurementGateDisplay', () => {
  it('turns MOQ and date reasons into operator actions', () => {
    const view = procurementGateDisplay({
      decision: 'needs_info',
      blocking: [],
      reasons: ['below_supplier_moq', 'missing_rfq_fields:deadline_date'],
    });
    expect(view.label).toBe('needs_info');
    expect(view.reasons.map((reason) => reason.code)).toEqual([
      'below_supplier_moq', 'missing_rfq_fields:deadline_date',
    ]);
    expect(view.reasons[0].action).toContain('Consolidate demand');
    expect(view.reasons[1].action).toContain('required-by date');
  });
});

describe('procurementDraftPending', () => {
  it('retries a committed case until its auto-draft materializes', () => {
    expect(procurementDraftPending({ state: 'COMMITTED', state_json: {} })).toBe(true);
    expect(procurementDraftPending({
      state: 'QUOTE_DRAFTED', state_json: { draft: { subject: 'RFQ' } },
    })).toBe(false);
    expect(procurementDraftPending(null)).toBe(false);
  });
});
