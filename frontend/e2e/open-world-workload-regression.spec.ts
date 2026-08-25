import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

async function send(page: import('@playwright/test').Page, text: string) {
  const input = page.getByPlaceholder('Type your message...');
  const responsePromise = page.waitForResponse(
    response => (
      /\/api\/v1\/chat\/(stream|query)$/.test(response.url())
      || /\/api\/v1\/shopping-cases\/interpretations$/.test(response.url())
    ),
    { timeout: 65_000 },
  );
  await input.fill(text);
  await input.press('Enter');
  let response = await responsePromise;
  if (/\/shopping-cases\/interpretations$/.test(response.url())) {
    if (response.status() !== 204) return response.json();
    response = await page.waitForResponse(
      candidate => /\/api\/v1\/chat\/(stream|query)$/.test(candidate.url()),
      { timeout: 65_000 },
    );
  }
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 60_000 });
  const body = await response.text();
  const payloads = body.split('\n')
    .filter(line => line.startsWith('data: '))
    .map(line => {
      try { return JSON.parse(line.slice(6)); } catch { return null; }
    })
    .filter(Boolean);
  return [...payloads].reverse().find(
    (payload: any) => payload?.decision_trace_id || payload?.trace_id,
  ) || {};
}

test('novel suitability request stays provisional and exposes a durable research plan', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-open-world-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const unresolved = await send(
    page,
    'I edit 8K RAW video and do colour-critical grading. I do not care about gaming FPS. Which laptop should I buy?',
  );
  const unresolvedTraceId = String(unresolved.decision_trace_id || unresolved.trace_id || '');
  expect(unresolvedTraceId).not.toBe('');
  expect(unresolved.qualification_authority ?? 'none').toBe('none');

  await expect(page.getByTestId('buyer-research-status')).toContainText(/external research is off/i);
  await expect(page.getByRole('button', { name: /Discover official sources/i })).toBeVisible();
  await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
  await expect(page.getByTestId('ambiguity-accounting')).toContainText(/external calls: 0/i);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await expect(modal.locator(`[title="${unresolvedTraceId}"]`)).toBeVisible();
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  const research = modal.getByTestId('workload-research-trace');
  await expect(research).toContainText(/8K RAW video/i);
  await expect(research).toContainText(/colour-critical grading/i);
  await expect(research).toContainText(/bounded research plan/i);
  await expect(research).toContainText(/Status:\s*(blocked|planned|not executed)/i);
  await expect(research).toContainText(/catalog recommendation|exploration/i);
  await page.screenshot({ path: '../.tmp-open-world-browser/coverage-gate.png', fullPage: true });
});

test('explicit furniture and pharmacy categories cannot inherit laptop shelves', async ({ page }) => {
  test.setTimeout(120_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-category-boundary-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  for (const request of [
    'I need an ergonomic standing desk and mesh office chair.',
    'I need ibuprofen and a blood pressure monitor.',
  ]) {
    const boundary = await send(page, request);
    expect(boundary.schema_version).toBe('catalog-boundary-v1');
    expect(boundary.catalog_boundary.status).toBe('out_of_category');
    expect(boundary.catalog_boundary.configuration_ids).toEqual([]);
    expect(boundary.provider_accounting).toEqual({ external_calls: 0, paid_calls: 0 });
    await expect(page.getByText(/outside this storefront's current catalog/i).last()).toBeVisible();
    await expect(page.getByTestId('ambiguity-exploration')).toHaveCount(0);
    const shelves = page.getByTestId('product-shelves');
    if (await shelves.count()) await expect(shelves.locator('article')).toHaveCount(0);
  }
});

test('novel publisher is approved case-only, fetched, reviewed, and reranked in one case', async ({ page }) => {
  test.setTimeout(240_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-publisher-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  await send(
    page,
    'I process large drone surveys in Agisoft Metashape. Only hardware officially supported by Agisoft is acceptable. Is this gaming laptop suitable?',
  );
  await expect(page.getByText(/Authorized recommendation/i)).toHaveCount(0);
  await expect(page.getByTestId('ambiguity-accounting')).toContainText(/external calls: 0/i);

  const discoveryResponse = page.waitForResponse(
    response => /\/api\/v1\/shopping-cases\/[^/]+\/research$/.test(response.url()),
    { timeout: 30_000 },
  );
  await page.getByRole('button', { name: /Discover official sources/i }).click();
  const discovery = await (await discoveryResponse).json();
  expect(discovery.status).toBe('publisher_resolution_required');
  expect(discovery.research.provider_accounting.discovery_calls).toBeGreaterThanOrEqual(1);
  expect(discovery.research.provider_accounting.official_origin_fetches).toBe(0);
  expect(discovery.research.provider_accounting.paid_calls).toBe(0);
  expect(discovery.research.candidates.length).toBeGreaterThan(0);
  expect(discovery.research.candidates[0].candidate_id).toMatch(/^pubcand-/);

  const agisoftCandidate = page.getByTestId('publisher-candidates').getByRole('listitem')
    .filter({ hasText: /System Requirements.*\(www\.agisoft\.com\)/i })
    .first();
  await expect(agisoftCandidate).toBeVisible();
  await expect(agisoftCandidate.getByRole('button', { name: 'Use for this case' })).toBeVisible();
  const approvalResponse = page.waitForResponse(
    response => /\/publisher-candidates\/[^/]+\/approve$/.test(response.url()),
    { timeout: 30_000 },
  );
  await agisoftCandidate.getByRole('button', { name: 'Use for this case' }).click();
  const approval = await (await approvalResponse).json();
  expect(approval.candidate.approval_scope).toBe('case_only');
  expect(approval.provider_accounting.official_origin_fetches).toBeGreaterThanOrEqual(1);
  expect(approval.provider_accounting.paid_calls).toBe(0);
  expect(approval.research_status).toBe('claims_pending_review');
  expect(approval.claims.length).toBeGreaterThan(0);
  expect(approval.qualification_authority).toBe('none');

  const review = page.getByTestId('buyer-requirement-review').last();
  await expect(review).toContainText(/exact publisher origin/i);
  const acceptanceResponse = page.waitForResponse(
    response => /\/requirement-proposals\/[^/]+\/accept$/.test(response.url()),
    { timeout: 30_000 },
  );
  await review.getByRole('button', { name: 'Accept case evidence' }).click();
  const accepted = await (await acceptanceResponse).json();
  expect(accepted.status).toBe('accepted_case_evidence');
  expect(accepted.qualification_authority).toBe('requirements');
  expect(accepted.cart_mutation).toBe('not_authorized');
  await expect(page.getByTestId('buyer-research-status'))
    .toContainText(/official requirements compiled/i);
  if (process.env.PORTFOLIO_RESEARCH_CERTIFICATE_PATH) {
    const before = (discovery?.product_shelves?.shelves || []).flatMap(
      (shelf: any) => (shelf.initial || []).map((item: any) => item?.product?.configuration_id),
    ).filter(Boolean);
    const after = (accepted?.product_shelves?.shelves || []).flatMap(
      (shelf: any) => (shelf.initial || []).map((item: any) => item?.product?.configuration_id),
    ).filter(Boolean);
    const retained = JSON.stringify(before) === JSON.stringify(after);
    const certificate: any = {
      schema_version: 'open-world-browser-research-certificate-v1',
      observed_at: new Date().toISOString(),
      execution: 'playwright_browser',
      fixture: false,
      prompt: 'I process large drone surveys in Agisoft Metashape. Only hardware officially supported by Agisoft is acceptable. Is this gaming laptop suitable?',
      case_id: accepted.case_id,
      trace_id: accepted.trace_id,
      consent: 'buyer_authorized_discovery_then_case_only_origin',
      discovery: {
        calls: discovery.research.provider_accounting.discovery_calls,
        paid_calls: discovery.research.provider_accounting.paid_calls,
        query_hashes: (discovery.research.receipts || []).map((row: any) => row.query_hash).filter(Boolean),
        receipts: discovery.research.receipts || [],
        candidate_count: discovery.research.candidates.length,
      },
      selected_origin: {
        url: approval.candidate.url,
        domain: approval.candidate.domain,
        approval_scope: approval.candidate.approval_scope,
        ownership: approval.candidate.publisher_ownership_status,
        verification: approval.candidate.publisher_origin_verification,
      },
      official_fetch: {
        calls: approval.provider_accounting.official_origin_fetches,
        paid_calls: approval.provider_accounting.paid_calls,
        receipts: (approval.research.receipts || []).filter(
          (row: any) => row.provider_capability === 'OFFICIAL_ORIGIN_FETCH',
        ),
      },
      claims: approval.claims.map((claim: any) => ({
        claim_id: claim.claim_id,
        attribute: claim.attribute,
        operator: claim.operator,
        value: claim.value,
        unit: claim.unit,
        citation_url: claim.citation_url,
        authority_status: claim.authority_status,
      })),
      buyer_acceptance: {
        status: accepted.status,
        qualification_authority: accepted.qualification_authority,
        accepted_claim_count: accepted.accepted_claims.length,
        cart_mutation: accepted.cart_mutation,
      },
      ranking: {
        before_configuration_ids: before,
        after_configuration_ids: after,
        outcome: retained ? 'retained' : 'reranked',
        reason: retained
          ? 'Accepted requirements did not change relative fit among the exact candidate configurations.'
          : 'Accepted cited requirement attributes changed deterministic exact-configuration fit.',
      },
      invariants: {
        paid_calls: 0,
        unsupported_dimensions: 'not_verified',
        supplier_send: 'not_authorized',
        cart_mutation: 'not_authorized',
      },
    };
    const canonical = JSON.stringify(certificate);
    certificate.seal = {
      algorithm: 'sha256',
      canonical_payload_sha256: createHash('sha256').update(canonical).digest('hex'),
      review_status: 'machine_generated_live_browser_certificate',
    };
    const target = resolve(process.env.PORTFOLIO_RESEARCH_CERTIFICATE_PATH);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, `${JSON.stringify(certificate, null, 2)}\n`, 'utf8');
  }
  await page.screenshot({ path: '../.tmp-open-world-browser/case-origin-rerank.png', fullPage: true });
});
