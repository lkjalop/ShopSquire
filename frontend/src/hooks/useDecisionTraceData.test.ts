import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

import { shoppingCaseIdFromTraceEvents, useDecisionTraceData } from './useDecisionTraceData';

it('ends a stalled read at the bounded audit deadline', async () => {
  vi.useFakeTimers();
  const request = vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(() => {}));
  try {
    const {result, unmount} = renderHook(() => useDecisionTraceData({active:true, caseId:'case-one', revision:2}));
    expect(result.current.status).toBe('loading');
    await act(async()=>{await vi.advanceTimersByTimeAsync(8000);});
    expect(result.current.status).toBe('unavailable');
    expect((request.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    expect(request).toHaveBeenCalledTimes(1);
    unmount();
  } finally { request.mockRestore(); vi.useRealTimers(); }
});

it('retries history only on an explicit request after a failed read', async () => {
  const request = vi.spyOn(globalThis, 'fetch')
    .mockRejectedValueOnce(new Error('transport unavailable'))
    .mockResolvedValueOnce({ok:true, json:async()=>({turn_history:[{commit_id:'one'}]})} as Response);
  try {
    const {result, unmount} = renderHook(() => useDecisionTraceData({active:true, caseId:'case-one', revision:2}));
    await waitFor(()=>expect(result.current.status).toBe('unavailable'));
    expect(request).toHaveBeenCalledTimes(1);
    act(()=>result.current.retry());
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    expect(request).toHaveBeenCalledTimes(2);
    expect(result.current.data.turn_history[0].commit_id).toBe('one');
    unmount();
  } finally { request.mockRestore(); }
});

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
