import { describe, expect, it } from 'vitest';

import { shoppingCaseIdFromTraceEvents } from './useDecisionTraceData';


describe('shoppingCaseIdFromTraceEvents', () => {
  it('uses the latest typed decision-run case reference', () => {
    expect(shoppingCaseIdFromTraceEvents([
      { payload: { case_id: 'case-old' } },
      { payload: { procurement_decision_run: { case_id: 'case-current' } } },
    ])).toBe('case-current');
  });

  it('does not invent a case from unrelated trace text', () => {
    expect(shoppingCaseIdFromTraceEvents([{ payload: { message: 'case maybe' } }])).toBeNull();
  });
});
