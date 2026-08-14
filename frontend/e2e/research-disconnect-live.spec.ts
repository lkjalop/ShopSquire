import { expect, test } from '@playwright/test';


test('buyer disconnect during live discovery does not strand backend responsiveness', async ({ page, request }) => {
  test.setTimeout(150_000);
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', `disconnect-${Date.now()}`);
  });
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');
  await input.fill(
    'Is this laptop suitable for an unfamiliar scientific solver whose official publisher requirements must be checked?',
  );
  await input.press('Enter');
  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 65_000 });
  const research = panel.getByRole('button', {
    name: /Discover official sources|Research approved sources/i,
  });
  const dispatched = page.waitForRequest(
    req => req.method() === 'POST' && /\/shopping-cases\/[^/]+\/research$/.test(req.url()),
    { timeout: 30_000 },
  );
  await research.click({ noWaitAfter: true });
  await dispatched;
  await page.context().close();

  const started = Date.now();
  const health = await request.get('http://127.0.0.1:8080/healthz', { timeout: 15_000 });
  expect(health.ok()).toBe(true);
  expect(Date.now() - started).toBeLessThan(15_000);
});

test('forced disconnect cooperatively stops undispatched discovery queries', async ({ page, request }) => {
  test.skip(process.env.LIVE_DISCONNECT_CERTIFICATION !== '1',
    'Requires the deliberately slow multi-query SearXNG certification profile.');
  test.setTimeout(150_000);
  await page.addInitScript(() => {
    localStorage.clear();
    sessionStorage.clear();
    sessionStorage.setItem('uid', `forced-disconnect-${Date.now()}`);
  });
  await page.goto('/');
  await page.getByRole('button', { name: /Ask Me/i }).click();
  const input = page.getByPlaceholder('Type your message...');
  await input.fill('Check official publisher requirements for an unfamiliar certified multiphysics solver.');
  await input.press('Enter');
  const panel = page.getByTestId('ambiguity-exploration');
  await expect(panel).toBeVisible({ timeout: 65_000 });
  const research = panel.getByRole('button', { name: /Discover official sources|Research approved sources/i });
  let traceId = '';
  const dispatched = page.waitForRequest(req => {
    const match = req.url().match(/\/shopping-cases\/sc-([^/]+)\/research$/);
    if (req.method() === 'POST' && match) {
      traceId = match[1];
      return true;
    }
    return false;
  }, { timeout: 30_000 });
  await research.click({ noWaitAfter: true });
  await dispatched;
  expect(traceId).not.toBe('');
  await expect.poll(async () => {
    const response = await request.get(`http://127.0.0.1:8080/api/v1/trace/${traceId}/events`);
    if (!response.ok()) return false;
    const body = await response.json();
    const events = Array.isArray(body) ? body : (body.events || []);
    return events.some((row: any) => (
      String(row?.event_type || '') === 'open_world_discovery_started'
      || String(row?.payload?._original_event_type || '') === 'open_world_discovery_started'
    ));
  }, { timeout: 30_000, intervals: [100, 250, 500] }).toBe(true);
  const cancellationDispatched = page.waitForRequest(req => (
    req.method() === 'POST' && /\/shopping-cases\/[^/]+\/research-cancel$/.test(req.url())
  ));
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  await cancellationDispatched;
  await page.context().close();

  await expect.poll(async () => {
    const response = await request.get(`http://127.0.0.1:8080/api/v1/trace/${traceId}/events`);
    if (!response.ok()) return null;
    const body = await response.json();
    const events = Array.isArray(body) ? body : (body.events || []);
    const event = [...events].reverse().find((row: any) => (
      String(row?.event_type || '') === 'open_world_discovery_completed'
      || String(row?.payload?._original_event_type || '') === 'open_world_discovery_completed'
    ));
    const payload = event?.payload || {};
    return payload?.cancellation?.requested ? payload : null;
  }, { timeout: 30_000, intervals: [250, 500, 1000] }).toMatchObject({
    execution_status: 'cancelled',
    cancellation: { requested: true },
    qualification_authority: 'none',
    cart_authority: 'none',
    provider_accounting: { paid_calls: 0 },
  });
});
