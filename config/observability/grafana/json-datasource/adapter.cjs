'use strict';
const http = require('node:http');
const { Buffer } = require('node:buffer');
const paths = { analytics: '/api/v1/admin/analytics?days=7', livefeed: '/api/v1/admin/compliance/live-feed?limit=50' };

function frames(mode, data, targets) {
  if (mode === 'analytics') {
    if (!data.series || typeof data.series !== 'object') throw Error('schema');
    return targets.map(({ target }) => ({ target, datapoints: (data.series[target] || [])
      .filter(p => Number.isFinite(p.count) && Number.isFinite(Date.parse(p.day)))
      .map(p => [p.count, Date.parse(p.day)]) }));
  }
  if (!Array.isArray(data.items)) throw Error('schema');
  return [{ type: 'table', columns: [
    { text: 'time', type: 'time' }, { text: 'type', type: 'string' },
    { text: 'summary', type: 'string' }, { text: 'tags', type: 'string' }, { text: 'controls', type: 'string' },
  ], rows: data.items.map(i => [Number.isFinite(Date.parse(i.time)) ? Date.parse(i.time) : null,
    i.type, i.summary, JSON.stringify(i.tags || {}), (i.controls || []).join(', ')]) }];
}
function createAdapter({ mode, apiBase, apiKey, timeoutMs = 5000, maxResponseBytes = 1048576 }) {
  if (!paths[mode]) throw Error('Unsupported adapter mode');
  if (!apiKey || /[\r\n]/.test(apiKey)) throw Error('API_KEY must be configured');
  const base = new URL(apiBase);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw Error('Invalid API_BASE');
  const upstream = new URL(base.href.replace(/\/$/, '') + paths[mode]);
  return http.createServer(async (req, res) => {
    const send = (status, data) => {
      if (!res.destroyed && !res.headersSent) { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); }
    };
    if (req.method === 'GET' && req.url === '/') return send(200, { status: 'ok', name: `shopsquire-${mode}` });
    if (req.method !== 'POST' || !['/search', '/query', '/annotations'].includes(req.url)) return send(404, { error: 'not_found' });
    let body;
    try {
      const chunks = []; let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 65536) { send(413, { error: 'request_too_large' }); req.resume(); return; }
        chunks.push(chunk);
      }
      body = JSON.parse(Buffer.concat(chunks).toString() || '{}');
      if (!body || Array.isArray(body) || typeof body !== 'object') throw Error('body');
      if (body.targets !== undefined && (!Array.isArray(body.targets) || body.targets.some(t => !t || typeof t.target !== 'string'))) throw Error('targets');
    } catch { return send(400, { error: 'invalid_json_request' }); }
    if (req.url === '/search') return send(200, mode === 'analytics' ? ['orders', 'decisions', 'security'] : ['compliance_live_feed']);
    if (req.url === '/annotations') return send(200, []);
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(upstream, { headers: { 'x-api-key': apiKey }, redirect: 'error', signal: controller.signal });
      if (!response.ok) { await response.body?.cancel(); return send(502, { error: 'upstream_rejected' }); }
      const chunks = []; let size = 0;
      for await (const chunk of response.body) {
        size += chunk.length;
        if (size > maxResponseBytes) { controller.abort(); return send(502, { error: 'upstream_response_too_large' }); }
        chunks.push(chunk);
      }
      send(200, frames(mode, JSON.parse(Buffer.concat(chunks).toString()), body.targets || []));
    } catch { send(controller.signal.aborted ? 504 : 502, { error: controller.signal.aborted ? 'upstream_timeout' : 'upstream_unavailable' }); }
    finally { clearTimeout(deadline); }
  });
}
function start(mode) {
  const server = createAdapter({ mode, apiBase: process.env.API_BASE || 'http://api:8080', apiKey: process.env.API_KEY });
  server.requestTimeout = 10000; server.headersTimeout = 10000;
  server.listen(Number(process.env.PORT || (mode === 'analytics' ? 3333 : 3334)), '0.0.0.0');
  return server;
}
module.exports = { createAdapter, start };
