import { expect, test } from '@playwright/test';


test('real backend seals a topology-neutral side-effect-free disturbance matrix', async ({ request }, testInfo) => {
  const baseUrl = process.env.DISTURBANCE_CERT_BASE_URL || 'http://127.0.0.1:8099';
  const now = '2026-08-17T00:00:00+00:00';
  const kinds = [
    'supplier_delay', 'stock_correction', 'price_change', 'buyer_quantity_change',
    'quote_expiry', 'supplier_rejection', 'supplier_substitute',
  ];
  const response = await request.post(`${baseUrl}/api/v1/certification/procurement/disturbances/evaluate`, {
    headers: { 'x-api-key': process.env.OWNER_API_KEY || 'local-owner-key' },
    data: {
      scenario: {
        scenario_id: 'playwright-live-topology-neutral',
        state: {
          schema_version: 'procurement_case_state.v1', case_id: 'browser-cert-case',
          revision: 4, objective: 'topology-neutral fleet', requested_quantity: 30,
          workloads: [], candidate_skus: [], destinations: [{
            location_ref: 'destination-token', location_kind: 'address_token', quantity: 30,
          }], policies: {}, research: {}, requirements: {}, fulfilment: {}, authority: {},
        },
        hidden_constraints: {}, supplies: [], demands: [], lanes: [],
        disturbances: kinds.map((kind) => ({
          disturbance_id: `browser-${kind}`, kind, case_id: 'browser-cert-case',
          expected_case_revision: 4, known_at: now, effective_at: now,
          evidence_ref: `browser-certification:${kind}`,
        })),
        permitted_actions: ['project', 'allocate'],
        expected: {
          no_external_calls: true, no_rfq_calls: true, no_cart_mutations: true,
          preserve_constraints: true, require_complete_allocation: false,
        },
      },
      knowledge_cutoff: now,
      evaluation_time: now,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const artifact = await response.json();
  expect(artifact.result.passed).toBe(true);
  expect(artifact.result.projections).toHaveLength(kinds.length);
  expect(artifact.provider_accounting).toEqual({
    external_calls: 0, rfq_calls: 0, cart_mutations: 0, paid_calls: 0,
  });
  expect(artifact.commercial_authority_granted).toBe(false);
  expect(artifact.artifact_sha256).toMatch(/^[a-f0-9]{64}$/);
  await testInfo.attach('sealed-disturbance-certificate.json', {
    body: Buffer.from(JSON.stringify(artifact, null, 2)),
    contentType: 'application/json',
  });
});
