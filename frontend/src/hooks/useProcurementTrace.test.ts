import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useProcurementTrace } from './useProcurementTrace';

vi.mock('../lib/api', () => ({ apiUrl: (value: string) => value, getSplitOffer: vi.fn().mockResolvedValue(null) }));
const props = { active: true, traceId: 'a', revision: '1', apiKey: '', canSeeOperatorDraft: false };
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;
afterEach(() => vi.unstubAllGlobals());

describe('procurement trace ownership', () => {
  it('reports missing case as not applicable, without a loading state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ cases: [] })));
    const { result, unmount } = renderHook(() => useProcurementTrace(props));
    await waitFor(() => expect(result.current.status).toBe('not_applicable'));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    unmount();
  });

  it.each([401, 404, 500])('reports HTTP %s as an error instead of an empty success', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({}, status)));
    const { result, unmount } = renderHook(() => useProcurementTrace(props));
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe(`http_${status}`);
    expect(result.current.loading).toBe(false);
    unmount();
  });

  it('ignores an old response even if the transport ignores abort', async () => {
    let resolveOld!: (value: Response) => void;
    const old = new Promise<Response>(resolve => { resolveOld = resolve; });
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) =>
      url.includes('/by-trace/a/') ? old : Promise.resolve(response({ cases: [] }))));
    const { result, rerender, unmount } = renderHook(value => useProcurementTrace(value), { initialProps: props });
    rerender({ ...props, traceId: 'b', revision: '2' });
    await waitFor(() => expect(result.current.status).toBe('not_applicable'));
    await act(async () => resolveOld(response({ cases: [{ case_id: 'old-case', state: 'DRAFT' }] })));
    expect(result.current.cases).toEqual([]);
    expect(result.current.key).toContain('b');
    expect(result.current.status).toBe('not_applicable');
    unmount();
  });
});
