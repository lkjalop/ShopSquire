import {expect, type BrowserContext} from '@playwright/test';
import {randomUUID} from 'node:crypto';

/** Ordinary native buyer, confined to the explicitly owned local browser run. */
export async function registerBuyer(context: BrowserContext): Promise<string> {
  const baseURL = process.env.PLAYWRIGHT_BASE_URL;
  if (!baseURL || !process.env.ROADMAP_TEST_ROOT || !process.env.ROADMAP_TEST_JWT_KEY
      || !['127.0.0.1', 'localhost'].includes(new URL(baseURL).hostname)) {
    throw new Error('registerBuyer requires the owned local browser harness');
  }
  const tenant = process.env.VITE_STOREFRONT_TENANT_ID;
  if (!tenant) throw new Error('An explicit storefront tenant is required');
  // Registration owns the browser identity. No merchant key or pre-signed JWT
  // is attached, and each invocation creates a separate durable buyer account.
  await context.setExtraHTTPHeaders({'x-tenant-id': tenant});
  const nonce = randomUUID();
  const response = await context.request.post(new URL('/api/v1/auth/register', baseURL).href, {
    data: {email: `browser-${nonce}@example.com`, password: `Fixture-${nonce}!`, name: 'Fictional test buyer'},
  });
  expect(response.ok(), `Native registration failed (${response.status()})`).toBe(true);
  const {user_id: uid} = await response.json();
  expect(typeof uid).toBe('string');
  expect(uid.length).toBeGreaterThan(0);
  const cookies = await context.cookies(baseURL);
  expect(cookies.some(cookie => ['shopsquire_session', 'shopsquire_access'].includes(cookie.name))).toBe(true);
  await context.addInitScript(subject => {
    // Playwright supplies a fresh context per test. Clearing storage on every
    // document would erase the application's case/epoch pointer on reload.
    sessionStorage.setItem('uid', subject);
  }, uid);
  return uid;
}
