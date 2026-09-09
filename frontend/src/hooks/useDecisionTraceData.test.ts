import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

import { shoppingCaseIdFromTraceEvents, useDecisionTraceData } from './useDecisionTraceData';

it('refreshes persisted history when the same case advances revision', async () => {
  const request = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ok:true, json:async()=>({turn_history:[]})} as Response);
  try {
    const {result, rerender, unmount} = renderHook(({revision}) => useDecisionTraceData({active:true, caseId:'case-one', revision}), {initialProps:{revision:2}});
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    rerender({revision:3});
    await waitFor(()=>expect(request).toHaveBeenCalledTimes(2));
    unmount();
  } finally { request.mockRestore(); }
});


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
