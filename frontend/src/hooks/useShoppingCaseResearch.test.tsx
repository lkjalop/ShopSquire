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

  it('owns same-case evidence and publisher mutations', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'accepted' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useShoppingCaseResearch());
    act(() => result.current.setAmbiguityExploration({
      schema_version: 'ambiguity-exploration-v1', case_id: 'case-3',
      retained_purpose: 'novel workload', status: 'provisional',
      research_plan_id: 'plan-3', interpretations: [], ambiguity_objects: [], shelves: [],
    } as any));

    await act(async () => {
      await result.current.submitManualSpecifications('buyer-1', 'RAM >= 32 GB');
      await result.current.resolveEvidenceSource(
        'buyer-1', { source_url: 'https://vendor.example/requirements' }, true,
      );
      await result.current.approvePublisherCandidate('buyer-1', {
        candidate_id: 'publisher-1', candidate_version: 1,
      });
    });

    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      expect.stringContaining('/shopping-cases/case-3/requirement-proposals/from-text'),
      expect.stringContaining('/shopping-cases/case-3/evidence-source-resolutions'),
      expect.stringContaining('/shopping-cases/case-3/publisher-candidates/publisher-1/approve'),
    ]);
  });

  it('applies only revision-matched durable interpretation SSE events', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({
          event_type: 'case_interpretation_completed',
          payload: {
            case_id: 'sc-case-4', case_revision: 2, job_id: 'sci-4',
            interpretations: [{ hypothesis_id: 'hyp-improved', label: 'Improved interpretation' }],
          },
        })}\n\n`));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true, body }));
    const { result } = renderHook(() => useShoppingCaseResearch());
    act(() => {
      result.current.setAmbiguityExploration({
        schema_version: 'ambiguity-exploration-v1', case_id: 'sc-case-4',
        retained_purpose: 'novel workload', status: 'provisional',
        research_plan_id: 'plan-4',
        interpretations: [{ hypothesis_id: 'hyp-fast', label: 'Fast interpretation' }],
        ambiguity_objects: [], shelves: [],
      } as any);
      result.current.setActiveShoppingCase({
        case_id: 'sc-case-4', retained_purpose: 'novel workload', uid: 'buyer-1',
        revision: 2, interpretation_job_id: 'sci-4',
      });
    });

    await waitFor(() => expect(
      result.current.ambiguityExploration?.interpretations?.[0]?.hypothesis_id,
    ).toBe('hyp-improved'));
    expect(result.current.ambiguityExploration?.interpretation_job).toMatchObject({
      job_id: 'sci-4', case_revision: 2, status: 'completed',
    });
  });
});
