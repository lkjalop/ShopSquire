import { test, expect } from '@playwright/test';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

async function send(page: import('@playwright/test').Page, text: string, requireChat = false) {
  const input = page.getByPlaceholder('Type your message...');
  // Register before the turn starts: the frontend can launch the idempotent
  // query fallback immediately after the SSE `in_progress` event, before this
  // helper has finished decoding the stream body.
  const queryFallbackPromise = requireChat
    ? page.waitForResponse(
        candidate => candidate.request().method() === 'POST'
          && /\/api\/v1\/chat\/query$/.test(candidate.url()),
        { timeout: 100_000 },
      ).catch(() => null)
    : Promise.resolve(null);
  const responsePromise = page.waitForResponse(
    response => (
      response.request().method() === 'POST'
      && (
        /\/api\/v1\/chat\/(stream|query)$/.test(response.url())
        || (!requireChat && /\/api\/v1\/shopping-cases\/interpretations$/.test(response.url()))
      )
    ),
    { timeout: 65_000 },
  );
  await input.fill(text);
  await input.press('Enter');
  let response = await responsePromise;
  if (/\/shopping-cases\/interpretations$/.test(response.url())) {
    if (response.status() !== 204) return response.json();
    response = await page.waitForResponse(
      candidate => (
        candidate.request().method() === 'POST'
        && /\/api\/v1\/chat\/(stream|query)$/.test(candidate.url())
      ),
      { timeout: 65_000 },
    );
  }
  await expect(page.getByTestId('stream-acknowledgement')).toBeHidden({ timeout: 60_000 });
  const decodePayloads = (body: string): any[] => {
    const decoded = body.split('\n')
      .filter(line => line.startsWith('data: '))
      .map(line => {
        try { return JSON.parse(line.slice(6)); } catch { return null; }
      })
      .filter(Boolean);
    // `/chat/query` is a JSON fallback while `/chat/stream` is SSE.  The same
    // live certificate helper must inspect either transport.
    if (decoded.length === 0) {
      try { decoded.push(JSON.parse(body)); } catch { /* assertion reports a missing receipt */ }
    }
    return decoded;
  };
  let payloads = decodePayloads(await response.text());
  // Long live-model turns deliberately close the SSE request with an
  // idempotent in-progress receipt; App then obtains the completed atomic
  // result through `/chat/query`.  Follow that documented transport handoff.
  if (payloads.some((payload: any) => payload?.status === 'in_progress')) {
    const fallbackResponse = await queryFallbackPromise;
    if (!fallbackResponse) throw new Error('chat_query_fallback_response_missing');
    response = fallbackResponse;
    payloads = decodePayloads(await response.text());
  }
  const reversed = [...payloads].reverse();
  // A URL-bearing chat turn can emit the normal execution projection before
  // the atomic source-intake receipt.  Prefer the latter so the certificate
  // assertion cannot accidentally inspect an earlier SSE event.
  return reversed.find((payload: any) => payload?.buyer_evidence_source_resolution)
  || reversed.find((payload: any) => (
    payload?.execution_state_envelope
    || payload?.workload_authorization
    || payload?.semantic_resolution
  )) || reversed.find(
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

  await expect(page.getByTestId('buyer-research-status')).toContainText(
    /external research has not produced evidence|no approved requirement source was established/i,
  );
  const discoverButton = page.getByRole('button', { name: /Discover official sources/i });
  if (unresolved.execution_state_envelope?.research_authority !== 'granted') {
    await expect(discoverButton).toBeVisible();
  }
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

test('held-out future-game alias resolves identity but cannot invent fit or budget sufficiency', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  const prompt = 'i need a laptop to play the new remastered heroes of might and magic 3? is 3000 enough?';
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-heldout-game-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const result = await send(page, prompt, true);
  const products = result.products || result.results || [];
  expect(products).toEqual([]);
  expect(String(result.assistant_message || result.message || '')).not.toMatch(/\b(ample|enough|insufficient)\b/i);
  expect(result.workload_authorization?.status || result.semantic_resolution?.catalog_authority)
    .toBe('blocked');
  expect(result.execution_state_envelope?.catalog_authority).toBe('blocked');
  expect(result.execution_state_envelope?.commerce_authority).toBe('none');
  // The exact utterance does not itself grant network authority. A deployment
  // may grant it through an enrolled tenant auto-research policy; identity can
  // still be resolved from the deterministic alias registry in either mode.
  expect(result.execution_state_envelope?.research_authority).toMatch(/required|granted/);
  if (result.execution_state_envelope?.research_authority === 'granted') {
    expect(result.execution_state_envelope?.evidence_status).toBe('identity_only');
    expect(result.workload_authorization?.evidence?.[0]?.resolved_name)
      .toBe('Heroes of Might and Magic III Remake');
    expect(result.workload_authorization?.evidence?.[0]?.identity_resolution?.authority)
      .toBe('identity_candidate_only');
  } else {
    expect(result.execution_state_envelope?.evidence_status).toBe('none');
    expect(result.workload_authorization?.evidence?.[0]?.resolved_name).toBeFalsy();
  }
  await expect(page.getByText(/\bAUD\s*3,?000\b.*\b(ample|enough|insufficient)\b/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);
  await expect(page.getByText(/No product is qualified until the material gap is resolved/i))
    .toBeVisible();
  if (result.execution_state_envelope?.research_authority === 'granted') {
    await expect(page.getByText(/Heroes of Might and Magic III Remake/i)).toBeVisible();
  }

  const certificate: any = {
    schema_version: 'heldout-future-game-browser-certificate-v1',
    execution: 'live_playwright_browser',
    fixture: false,
    prompt,
    trace_id: result.decision_trace_id || result.trace_id,
    workload_authority: result.workload_authorization || null,
    execution_state: result.execution_state_envelope || null,
    control_faults: result.control_faults || [],
    invariants: {
      products_presented: products.length,
      budget_sufficiency_claimed: false,
      commerce_authority: 'none',
    },
  };
  certificate.seal = createHash('sha256').update(JSON.stringify(certificate)).digest('hex');
  await testInfo.attach('heldout-future-game-browser-certificate.json', {
    body: Buffer.from(`${JSON.stringify(certificate, null, 2)}\n`),
    contentType: 'application/json',
  });
});

test('first-turn Emulate3D URL creates its case and source-security receipt without a bridge race', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-emulate-link-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const result = await send(page,
    'I need a computer for Rockwell Emulate3D digital twin simulations. Official link: '
    + 'https://store.sim3d.com/demo3d_2025/system_requirements', true);
  const source = result.buyer_evidence_source_resolution;

  expect(source.case_id).toBe(result.ambiguity_exploration.case_id);
  expect(source.resolution.status).toBe('resolved');
  expect(source.resolution.selected_source_id).toBe('rockwell_emulate3d_official_requirements');
  expect(source.research_status).toMatch(/not_authorized|claims_pending_review/);
  if (source.research_status === 'not_authorized') {
    expect(source.provider_accounting).toEqual({ external_calls: 0, paid_calls: 0 });
  } else {
    expect(source.provider_accounting.official_origin_fetches).toBeGreaterThanOrEqual(1);
    expect(source.claims.length).toBeGreaterThan(0);
  }
  expect(source.source_intake_certificate).toMatchObject({
    case_id: source.case_id,
    security: {
      url_syntax: 'accepted_https_no_credentials',
      publisher_authority: 'enrolled',
      arbitrary_submitted_path_fetch_allowed: false,
    },
  });
  expect(source.source_intake_certificate.execution.network_execution)
    .toBe(source.research_status !== 'not_authorized');
  expect(source.cart_mutation).toBe('not_authorized');
  expect(source.supplier_send).toBe('not_authorized');
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0);

  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  const receipt = modal.getByTestId('source-intake-certificate');
  await expect(receipt).toContainText(
    /source intake: resolved.*safety (?:canonical fetch eligible|observed untrusted content pending compilation)/i,
  );
});

test('digital twin to Heroes III Remake supersedes evidence and consent but retains budget', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-digital-twin-heroes-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const first = await send(page,
    'I need an AUD 3000 computer for a digital twin. Link: https://store.sim3d.com/demo3d_2025/system_requirements',
    true);
  const firstCase = first.ambiguity_exploration.case_id;
  expect(first.buyer_evidence_source_resolution.resolution.status).toBe('resolved');

  const switched = await send(page,
    'I want a laptop to play the new remastered Heroes of Might and Magic 3.', true);
  expect(switched.ambiguity_exploration.case_id).not.toBe(firstCase);
  expect(switched.buyer_evidence_source_resolution ?? null).toBeNull();
  expect(switched.execution_state_envelope.commerce_authority).toBe('none');
  // Local demo policy authorizes research on each current turn. The boundary
  // receipt distinguishes that fresh grant from inherited consent.
  expect(switched.subject_switch_boundary).toMatchObject({
    schema_version: 'subject-switch-boundary-v1',
    research_authority: 'granted_on_replacement_turn',
    commerce_authority: 'none',
  });
  expect(JSON.stringify(switched)).not.toMatch(/rockwell_emulate3d_official_requirements/i);
  expect(switched.confirmed_slots?.budget_max || switched.confirmed_slots?.budget).toBeTruthy();
});

test('Heroes III Remake to BG3 resolves the new canonical Steam identity', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-heroes-bg3-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const heroes = await send(page,
    'I want a laptop to play the new remastered Heroes of Might and Magic 3. Is AUD 2500 enough?', true);
  const heroesCase = heroes.ambiguity_exploration.case_id;
  const bg3 = await send(page,
    "What about Baldur's Gate 3? You may check the enrolled official requirements.", true);
  expect(bg3.ambiguity_exploration?.case_id || bg3.shopping_case_id).not.toBe(heroesCase);
  const evidence = bg3.workload_authorization?.evidence || [];
  expect(evidence.some((item: any) => (
    item.canonical_title === "Baldur's Gate 3"
    && item.publisher === 'Larian Studios'
    && String(item.app_id) === '1086940'
    && item.release_state === 'released'
    && item.requirements_completeness === 'minimum_and_recommended'
  ))).toBe(true);
  expect(JSON.stringify(bg3)).not.toMatch(/Heroes of Might and Magic III Remake/);
});

test('unenrolled Larian URL is rejected with a visible zero-fetch security receipt', async ({ page }) => {
  test.setTimeout(180_000);
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  await page.addInitScript((uid) => {
    localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem('uid', uid);
  }, `enterprise-e2e-larian-reject-${suffix}`);
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();

  const result = await send(page,
    "I want a laptop for Baldur's Gate 3. Use https://larian.com/support/faqs/baldurs-gate-3?token=do-not-store",
    true);
  const source = result.buyer_evidence_source_resolution;
  expect(source.resolution.status).toBe('not_enrolled');
  expect(source.provider_accounting).toEqual({ external_calls: 0, paid_calls: 0 });
  expect(JSON.stringify(source)).not.toContain('do-not-store');
  expect(source.source_intake_certificate.security).toMatchObject({
    publisher_authority: 'not_enrolled',
    arbitrary_submitted_path_fetch_allowed: false,
  });
  await expect(page.getByText(/not an enrolled canonical source/i)).toBeVisible();
  await page.getByTitle('Decision Trace').click();
  const modal = page.getByTestId('decision-trace-modal');
  await modal.getByRole('button', { name: /^Research & Fit/ }).click();
  await modal.getByRole('tab', { name: /Research Breakdown/ }).click();
  await expect(modal.getByTestId('source-intake-certificate')).toContainText(/source intake: not enrolled/i);
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
