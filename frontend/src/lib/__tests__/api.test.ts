/**
 * api.ts — cart error surfacing (T2) + consumer-signal emitters (T5). Mocks global fetch with a plain
 * Response-like object so no network/jsdom-Response dependency is needed.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { addCartItem, setCartItemQty, emitConsumerSignal, emitPageView } from '../api';

function resp(body: any, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as any;
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('addCartItem error surfacing (T2)', () => {
  it('throws a readable message (not "[object Object]") for a 409 object detail', async () => {
    fetchMock.mockResolvedValue(resp({ detail: { error: 'insufficient_stock', available: 5, requested: 10 } }, 409));
    await expect(addCartItem('u', 'SKU-1', 10)).rejects.toThrow(/insufficient_stock/);
  });
});

describe('setCartItemQty allow_sourcing (T4)', () => {
  it('sends allow_sourcing=true in the PUT body when requested', async () => {
    fetchMock.mockResolvedValue(resp({ items: [] }, 200));
    await setCartItemQty('u', 'SKU-1', 15, true);
    const opts = fetchMock.mock.calls[0][1] as any;
    expect(JSON.parse(opts.body).allow_sourcing).toBe(true);
  });
  it('defaults allow_sourcing to false for the normal stepper', async () => {
    fetchMock.mockResolvedValue(resp({ items: [] }, 200));
    await setCartItemQty('u', 'SKU-1', 2);
    const opts = fetchMock.mock.calls[0][1] as any;
    expect(JSON.parse(opts.body).allow_sourcing).toBe(false);
  });
});

describe('consumer-signal emitters (T5, Track 2b)', () => {
  it('emitConsumerSignal POSTs to /consumer/ingest with the action + a session id', () => {
    fetchMock.mockResolvedValue(resp({ ok: true }, 200));
    emitConsumerSignal('u', 'checkout', {});
    expect(fetchMock).toHaveBeenCalled();
    const [url, opts] = fetchMock.mock.calls[0] as any;
    expect(String(url)).toContain('/api/v1/consumer/ingest');
    const body = JSON.parse((opts as any).body);
    expect(Array.isArray(body)).toBe(true);
    expect(body[0].action).toBe('checkout');
    expect(body[0].session_id).toBeTruthy();
  });

  it('emitPageView emits a single page_view (guarded once per load)', () => {
    fetchMock.mockResolvedValue(resp({ ok: true }, 200));
    emitPageView('u');
    emitPageView('u');
    const pageViews = fetchMock.mock.calls.filter((c: any) => {
      try { return JSON.parse(c[1].body)[0].action === 'page_view'; } catch { return false; }
    });
    expect(pageViews.length).toBe(1);
  });
});
