import { expect, test } from '@playwright/test';

test('shopping-case panel and Decision Trace consume the same truth projection', async ({ page }) => {
  const uid = `case-truth-${Date.now()}`;
  const purpose = 'I need to simulate a PLC-controlled factory and cyberattacks against the OT network.';
  const headers = {
    'x-api-key': 'local-developer-key',
    'x-tenant-id': 'default',
  };

  const created = await page.request.post('/api/v1/shopping-cases/interpretations', {
    headers,
    data: { uid, retained_purpose: purpose },
  });
  expect(created.status()).toBe(200);
  const panel = await created.json();
  const panelTruth = panel.ambiguity_exploration;

  const traceResponse = await page.request.get(
    `/api/v1/trace/${encodeURIComponent(panel.trace_id)}/events`,
    { headers },
  );
  expect(traceResponse.ok()).toBeTruthy();
  const trace = await traceResponse.json();
  const projected = [...trace.events].reverse().find(
    (event: any) => event.event_type === 'ambiguity_exploration_projected',
  );
  expect(projected).toBeTruthy();

  for (const field of [
    'case_id', 'trace_id', 'retained_purpose', 'status', 'interpretations',
    'execution', 'evidence', 'decision', 'provider_accounting',
    'research_plan_id', 'ambiguity_objects', 'research_obligations',
  ]) {
    expect(projected.payload[field], `trace drifted on ${field}`).toEqual(panelTruth[field]);
  }
});
