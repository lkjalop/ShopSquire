import { describe, expect, it, vi } from 'vitest';

import { http } from './client';

describe('admin API request deadlines', () => {
  it('aborts a request when its explicit deadline expires', async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(http('/api/v1/test/slow', { timeoutMs: 10 })).rejects.toMatchObject({
      name: 'TimeoutError',
    });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);

    vi.unstubAllGlobals();
  });

  it('forwards a caller cancellation into the internal deadline signal', async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
    }));
    vi.stubGlobal('fetch', fetchMock);
    const caller = new AbortController();
    const request = http('/api/v1/test/cancel', { signal: caller.signal, timeoutMs: 5_000 });
    caller.abort(new DOMException('caller cancelled', 'AbortError'));

    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);

    vi.unstubAllGlobals();
  });
});
