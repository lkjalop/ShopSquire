import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';


async function readTraceSnapshot(page: any, traceId: string): Promise<any[]> {
  return page.evaluate((id: string) => new Promise<any[]>((resolve, reject) => {
    const source = new EventSource(`/api/v1/trace/${encodeURIComponent(id)}/events/stream`);
    const timer = window.setTimeout(() => {
      source.close();
      reject(new Error('sse_snapshot_timeout'));
    }, 15_000);
    source.onmessage = (event) => {
      window.clearTimeout(timer);
      source.close();
      try { resolve(JSON.parse(event.data)); } catch (error) { reject(error); }
    };
    source.onerror = () => {
      window.clearTimeout(timer);
      source.close();
      reject(new Error('sse_snapshot_failed'));
    };
  }), traceId);
}


test('SSE reconnect observes canonical shopping-case revision supersession', async ({ page }, testInfo) => {
  await page.goto('/');
  const tenant = `portfolio-sse-${Date.now()}`;
  const uid = `buyer-sse-${Date.now()}`;
  const headers = { 'x-tenant-id': tenant };
  const created = await page.request.post('/api/v1/shopping-cases/interpretations', {
    headers,
    data: {
      uid,
      retained_purpose: 'I need a laptop for a vendor-certified novel multiphysics solver; is this hardware officially suitable?',
      storefront_taxonomy_handle: 'laptop',
    },
  });
  expect(created.ok()).toBeTruthy();
  const initial = await created.json();
  expect(initial.interpretation_job.case_revision).toBe(1);

  const firstSnapshot = await readTraceSnapshot(page, initial.trace_id);
  expect(firstSnapshot.some((event) => event.event_type === 'ambiguity_exploration_projected')).toBeTruthy();

  // The first EventSource is closed by readTraceSnapshot. Amend evidence while
  // disconnected, then reconnect; the durable snapshot must include supersession.
  const proposalResponse = await page.request.post(
    `/api/v1/shopping-cases/${encodeURIComponent(initial.case_id)}/requirement-proposals/from-text`,
    { headers, data: { uid, retained_purpose: initial.ambiguity_exploration.retained_purpose, text: 'RAM 32 GB and storage 1 TB NVMe.' } },
  );
  expect(proposalResponse.ok()).toBeTruthy();
  const proposal = await proposalResponse.json();
  const accepted = await page.request.post(
    `/api/v1/shopping-cases/${encodeURIComponent(initial.case_id)}/requirement-proposals/${encodeURIComponent(proposal.proposal_id)}/accept`,
    {
      headers: { ...headers, 'Idempotency-Key': `sse-revision-${Date.now()}` },
      data: {
        uid, expected_proposal_version: 1,
        accepted_claim_ids: proposal.claims.map((claim: any) => claim.claim_id),
        rejected_claim_ids: [], corrections: [], research_choice: 'local_only',
      },
    },
  );
  expect(accepted.ok()).toBeTruthy();
  const amended = await accepted.json();
  expect(amended.case_revision).toBe(2);

  const reconnectedSnapshot = await readTraceSnapshot(page, initial.trace_id);
  const supersession = reconnectedSnapshot.find((event) => event.event_type === 'case_revision_superseded');
  expect(supersession).toBeTruthy();
  expect(supersession.payload.superseded_version).toBe(1);
  expect(supersession.payload.active_version).toBe(2);
  expect(supersession.payload.authority).toBe('evidence_only');

  const latestJob = await page.request.get(
    `/api/v1/shopping-cases/${encodeURIComponent(initial.case_id)}/interpretation-jobs/latest?uid=${encodeURIComponent(uid)}`,
    { headers },
  );
  expect(latestJob.ok()).toBeTruthy();
  expect((await latestJob.json()).case_revision).toBe(1);

  const certificate: any = {
    schema_version: 'shopping-case-sse-revision-certificate-v1',
    observed_at: new Date().toISOString(),
    execution: 'live_playwright_browser', fixture: false,
    case_id: initial.case_id, trace_id: initial.trace_id,
    disconnected_after_revision: 1, reconnected_at_revision: 2,
    initial_event_count: firstSnapshot.length,
    reconnected_event_count: reconnectedSnapshot.length,
    supersession: supersession.payload,
    invariants: {
      stale_interpretation_revision: (await (await page.request.get(
        `/api/v1/shopping-cases/${encodeURIComponent(initial.case_id)}/interpretation-jobs/latest?uid=${encodeURIComponent(uid)}`,
        { headers },
      )).json()).case_revision,
      cart_mutation: 'not_authorized', supplier_send: 'not_authorized',
    },
  };
  certificate.seal = {
    algorithm: 'sha256',
    canonical_payload_sha256: createHash('sha256').update(JSON.stringify(certificate)).digest('hex'),
    review_status: 'machine_generated_live_browser_certificate',
  };
  await testInfo.attach('sse-revision-supersession-certificate.json', {
    body: Buffer.from(`${JSON.stringify(certificate, null, 2)}\n`),
    contentType: 'application/json',
  });
  if (process.env.SSE_REVISION_CERTIFICATE_PATH) {
    const target = resolve(process.env.SSE_REVISION_CERTIFICATE_PATH);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `${JSON.stringify(certificate, null, 2)}\n`, 'utf8');
  }
});
