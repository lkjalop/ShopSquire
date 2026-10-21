import { afterEach, expect, it, vi } from 'vitest';
import { fetchTrustedClaims, fetchSecurityAttackTimeseries, fetchSecurityGeoAsnTrends } from '../api';

afterEach(() => vi.unstubAllGlobals());

it('keeps the trusted-claims envelope and explicit filters', async () => {
  const body = { agent_name: 'agent-a', claim_type: 'stock', count: 1,
    claims: [{ id: 'c1', agent_name: 'agent-a', claim_type: 'stock', claim_key: 'sku', claim_value: 2, trust_score: .9, confidence: .8 }] };
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
  vi.stubGlobal('fetch', fetcher);
  const result = await fetchTrustedClaims({ agentName: 'agent-a', claimType: 'stock' });
  const url = String(fetcher.mock.calls[0][0]);
  expect(url).toContain('agent_name=agent-a');
  expect(url).toContain('claim_type=stock');
  expect(result.claims[0].claim_key).toBe('sku');
  expect(result.count).toBe(1);
});

it('sends the supported seven-day security window', async () => {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
  vi.stubGlobal('fetch', fetcher);
  await fetchSecurityAttackTimeseries(168, 8000);
  await fetchSecurityGeoAsnTrends(168, 4000);
  for (const call of fetcher.mock.calls) expect(String(call[0])).toContain('hours=168');
});
