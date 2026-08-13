import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useShoppingCaseResearch } from './useShoppingCaseResearch';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('useShoppingCaseResearch', () => {
  it('dispatches the durable plan and records completion', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'researched', trace_id: 'trace-1' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useShoppingCaseResearch());
    act(() => result.current.setAmbiguityExploration({
      schema_version: 'ambiguity-exploration-v1',
      case_id: 'case-1',
      retained_purpose: 'novel workload',
      status: 'provisional',
      research_plan_id: 'plan-1',
      interpretations: [{ hypothesis_id: 'hyp-1', label: 'Hypothesis one' }],
      ambiguity_objects: [{ ambiguity_id: 'amb-1', label: 'Unknown publisher' }],
      shelves: [],
    } as any));

    let payload: any;
    await act(async () => {
      payload = await result.current.executeResearch({ uid: 'buyer-1' });
    });

    expect(payload.status).toBe('researched');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const options = fetchMock.mock.calls[0][1];
    expect(JSON.parse(options.body)).toMatchObject({
      research_plan_id: 'plan-1',
      ambiguity_object_ids: ['amb-1'],
      hypothesis_ids: ['hyp-1'],
      research_authorized: true,
    });
    expect(result.current.researchState).toBe('completed');
  });

  it('aborts at the bounded deadline', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })));
    const { result } = renderHook(() => useShoppingCaseResearch());
    act(() => result.current.setAmbiguityExploration({
      schema_version: 'ambiguity-exploration-v1', case_id: 'case-2', retained_purpose: 'novel',
      status: 'provisional', research_plan_id: 'plan-2', interpretations: [], ambiguity_objects: [], shelves: [],
    } as any));

    let request: Promise<any>;
    act(() => {
      request = result.current.executeResearch({ uid: 'buyer-1', deadlineMs: 25 })
        .then(() => ({ resolved: true }), (error) => ({ error }));
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(30); });
    await expect(request!).resolves.toMatchObject({ error: { name: 'AbortError' } });
    expect(result.current.researchState).toBe('timed_out');
  });
});
