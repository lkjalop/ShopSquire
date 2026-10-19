import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import LoginModal from '../LoginModal';

afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

test.each(['login', 'register'])('%s uses the storefront tenant for native authentication', async (mode) => {
  vi.stubEnv('VITE_STOREFRONT_TENANT_ID', 'synthetic-electronics');
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({user_id:'buyer',role:'buyer'})});
  vi.stubGlobal('fetch', fetcher);
  const onLogin = vi.fn();
  render(<LoginModal onClose={() => {}} onLogin={onLogin} />);
  if (mode === 'register') {
    fireEvent.click(screen.getByRole('button', {name:'Register'}));
    fireEvent.change(screen.getByPlaceholderText('Name'), {target:{value:'Buyer'}});
  }
  fireEvent.change(screen.getByPlaceholderText('Email'), {target:{value:'buyer@example.invalid'}});
  fireEvent.change(screen.getByPlaceholderText('Password'), {target:{value:'Test-only-482!'}});
  fireEvent.click(screen.getByRole('button', {name: mode === 'login' ? 'Login' : 'Register'}));
  await waitFor(() => expect(onLogin).toHaveBeenCalled());
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toContain('/auth/' + mode);
  expect(options.headers['x-tenant-id']).toBe('synthetic-electronics');
  expect(options.credentials).toBe('include');
});
