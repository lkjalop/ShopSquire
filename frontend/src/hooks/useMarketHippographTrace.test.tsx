import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useMarketHippographTrace } from './useMarketHippographTrace';

afterEach(() => vi.unstubAllGlobals());

describe('useMarketHippographTrace', () => {
  it('loads operator health only while the market panel is active', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ status: 'observed', sources: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const matcher = (event: any, expected: string) => event.event_type === expected;
    const { result, rerender } = renderHook(
      ({ active }) => useMarketHippographTrace({
        active, events: [{ event_type: 'market_projection', payload: { sku: 'A' } }],
        trace: null, apiKey: 'owner-key', eventMatcher: matcher,
      }),
      { initialProps: { active: false } },
    );
    expect(fetchMock).not.toHaveBeenCalled();
    rerender({ active: true });
    await waitFor(() => expect(result.current.connectorHealthStatus).toBe('available'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.marketProjectionEvents).toHaveLength(1);
  });

  it('does not request operator data without operator credentials', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useMarketHippographTrace({
      active: true, events: [], trace: null, apiKey: '',
      eventMatcher: (event, expected) => event.event_type === expected,
    }));
    act(() => undefined);
    expect(result.current.connectorHealthStatus).toBe('not_requested');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
