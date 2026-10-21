import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { describe, expect, it, vi } from 'vitest';

async function withLocalResponse(
  status: number,
  delay: number,
  check: (client: typeof import('./client')) => Promise<void>,
) {
  const pending = new Set<ReturnType<typeof setTimeout>>();
  const server = createServer((_request, response) => {
    response.writeHead(status, { 'Content-Type': 'application/json' });
    response.flushHeaders();
    const timer = setTimeout(() => {
      pending.delete(timer);
      response.end(JSON.stringify({ ok: true, detail: 'owned response' }));
    }, delay);
    pending.add(timer);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    vi.stubEnv('VITE_API_BASE', `http://127.0.0.1:${(server.address() as AddressInfo).port}`);
    vi.resetModules();
    await check(await import('./client'));
  } finally {
    vi.unstubAllEnvs();
    for (const timer of pending) clearTimeout(timer);
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

describe('admin deadlines cover real HTTP bodies', () => {
  it.each([200, 503])('keeps its deadline while reading a slow %i JSON body', async status => {
    await withLocalResponse(status, 250, async client => {
      await expect(client.http('/body', { timeoutMs: 20 })).rejects.toMatchObject({ name: 'TimeoutError' });
    });
  });

  it('keeps its deadline through a download body', async () => {
    await withLocalResponse(200, 250, async client => {
      const download = (async () => {
        const response = await client.httpResponse('/download', { timeoutMs: 20 });
        return response.text();
      })();
      await expect(download).rejects.toMatchObject({ name: 'TimeoutError' });
    });
  });

  it('preserves successful JSON and downloadable response content', async () => {
    await withLocalResponse(200, 0, async client => {
      await expect(client.http('/json', { timeoutMs: 1000 })).resolves.toMatchObject({ ok: true });
      const response = await client.httpResponse('/download', { timeoutMs: 1000 });
      expect(response.headers.get('content-type')).toBe('application/json');
      await expect(response.json()).resolves.toMatchObject({ ok: true });
    });
  });
});
