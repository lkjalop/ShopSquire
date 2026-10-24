'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { createAdapter } = require('./adapter.cjs');
async function listen(server, t) {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  return `http://127.0.0.1:${server.address().port}`;
}
async function fixture(t, handler, options = {}) {
  const upstream = await listen(http.createServer(handler), t);
  const adapter = await listen(createAdapter({ mode: 'analytics', apiBase: upstream, apiKey: 'test-only', ...options }), t);
  return (data = { targets: [{ target: 'orders' }] }) => fetch(adapter + '/query', { method: 'POST', body: JSON.stringify(data) });
}
test('requires explicit credentials and refuses credentialed upstream URLs', () => {
  assert.throws(() => createAdapter({ mode: 'analytics', apiBase: 'http://127.0.0.1' }), /API_KEY/);
  assert.throws(() => createAdapter({ mode: 'analytics', apiBase: 'http://user:pass@127.0.0.1', apiKey: 'key' }), /API_BASE/);
});
test('real HTTP analytics preserves authenticated upstream data', async t => {
  const query = await fixture(t, (req, res) => {
    assert.equal(req.headers['x-api-key'], 'test-only'); assert.equal(req.url, '/api/v1/admin/analytics?days=7');
    res.end(JSON.stringify({ series: { orders: [{ count: 2, day: '2026-10-25' }] } }));
  });
  const response = await query(); assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), [{ target: 'orders', datapoints: [[2, Date.parse('2026-10-25')]] }]);
});
test('upstream authentication failure is explicit and sanitized', async t => {
  const query = await fixture(t, (_req, res) => { res.writeHead(401); res.end('private connection secret'); });
  const response = await query(); assert.equal(response.status, 502); assert.deepEqual(await response.json(), { error: 'upstream_rejected' });
});
test('total deadline bounds a hanging upstream', async t => {
  const query = await fixture(t, () => {}, { timeoutMs: 100 });
  const response = await query(); assert.equal(response.status, 504); assert.deepEqual(await response.json(), { error: 'upstream_timeout' });
});
test('malformed, oversized and redirected upstream responses fail visibly', async t => {
  for (const variant of ['json', 'size', 'redirect']) {
    const query = await fixture(t, (_req, res) => {
      if (variant === 'redirect') res.writeHead(302, { location: 'http://127.0.0.1:1' });
      res.end(variant === 'size' ? 'x'.repeat(200) : 'bad-json');
    }, { maxResponseBytes: 100 });
    assert.equal((await query()).status, 502);
  }
});
test('live feed keeps absent timestamps unknown', async t => {
  const query = await fixture(t, (_req, res) => res.end(JSON.stringify({ items: [{ type: 'review', summary: 'fixture' }] })), { mode: 'livefeed' });
  const response = await query(); assert.equal(response.status, 200); assert.equal((await response.json())[0].rows[0][0], null);
});
test('malformed targets are rejected before contacting upstream', async t => {
  const query = await fixture(t, () => assert.fail('upstream should not be called'));
  assert.equal((await query({ targets: [null] })).status, 400);
});
