/**
 * frontend/src/store/__tests__/stores.test.ts
 * Vitest unit tests for the Zustand stores.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useCartStore, useAuthStore, useChatStore } from '../index';

// Reset stores between tests to avoid bleed-over
beforeEach(() => {
  useCartStore.setState({ cart: null, loading: false, error: null });
  useAuthStore.setState({ user: null, token: null, isAuthenticated: false });
  useChatStore.setState({ messages: [], sessionId: null, isOpen: false, isLoading: false, currentTraceId: null });
});

// ── Cart store ────────────────────────────────────────────────────────────

describe('useCartStore', () => {
  it('sets cart correctly', () => {
    const cart = { cart_id: 'c1', items: [{ sku: 'sku-1', quantity: 2, price_cents: 999 }], subtotal_cents: 1998, currency: 'USD' };
    useCartStore.getState().setCart(cart);
    expect(useCartStore.getState().cart).toEqual(cart);
    expect(useCartStore.getState().error).toBeNull();
  });

  it('optimisticRemove removes an item', () => {
    const cart = {
      cart_id: 'c1',
      items: [
        { sku: 'sku-1', quantity: 1, price_cents: 500 },
        { sku: 'sku-2', quantity: 2, price_cents: 300 },
      ],
      subtotal_cents: 1100,
      currency: 'USD',
    };
    useCartStore.getState().setCart(cart);
    useCartStore.getState().optimisticRemove('sku-1');
    const items = useCartStore.getState().cart?.items ?? [];
    expect(items).toHaveLength(1);
    expect(items[0].sku).toBe('sku-2');
    expect(useCartStore.getState().cart?.subtotal_cents).toBe(600);
  });

  it('optimisticClear empties the cart', () => {
    const cart = {
      cart_id: 'c1',
      items: [{ sku: 'x', quantity: 1, price_cents: 100 }],
      subtotal_cents: 100,
      currency: 'USD',
    };
    useCartStore.getState().setCart(cart);
    useCartStore.getState().optimisticClear();
    expect(useCartStore.getState().cart?.items).toHaveLength(0);
    expect(useCartStore.getState().cart?.subtotal_cents).toBe(0);
  });

  it('setLoading updates loading flag', () => {
    useCartStore.getState().setLoading(true);
    expect(useCartStore.getState().loading).toBe(true);
    useCartStore.getState().setLoading(false);
    expect(useCartStore.getState().loading).toBe(false);
  });

  it('setError stores error message', () => {
    useCartStore.getState().setError('network_error');
    expect(useCartStore.getState().error).toBe('network_error');
  });
});

// ── Auth store ────────────────────────────────────────────────────────────

describe('useAuthStore', () => {
  it('login sets user and auth state', () => {
    const user = { uid: 'u1', role: 'buyer', email: 'test@example.com' };
    useAuthStore.getState().login(user, 'tok123');
    const state = useAuthStore.getState();
    expect(state.user).toEqual(user);
    expect(state.token).toBe('tok123');
    expect(state.isAuthenticated).toBe(true);
  });

  it('logout clears auth state', () => {
    useAuthStore.getState().login({ uid: 'u1', role: 'buyer' }, 'tok');
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.token).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it('updateRole changes the role', () => {
    useAuthStore.getState().login({ uid: 'u1', role: 'buyer' }, 'tok');
    useAuthStore.getState().updateRole('merchant');
    expect(useAuthStore.getState().user?.role).toBe('merchant');
  });

  it('updateRole is a no-op when not logged in', () => {
    useAuthStore.getState().updateRole('admin');
    expect(useAuthStore.getState().user).toBeNull();
  });
});

// ── Chat store ────────────────────────────────────────────────────────────

describe('useChatStore', () => {
  it('addMessage appends a message with id and timestamp', () => {
    useChatStore.getState().addMessage({ role: 'user', content: 'hello' });
    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe('hello');
    expect(messages[0].role).toBe('user');
    expect(messages[0].id).toBeTruthy();
    expect(messages[0].timestamp).toBeGreaterThan(0);
  });

  it('clearMessages empties the list', () => {
    useChatStore.getState().addMessage({ role: 'user', content: 'hi' });
    useChatStore.getState().addMessage({ role: 'assistant', content: 'hello' });
    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it('setOpen toggles overlay', () => {
    useChatStore.getState().setOpen(true);
    expect(useChatStore.getState().isOpen).toBe(true);
    useChatStore.getState().setOpen(false);
    expect(useChatStore.getState().isOpen).toBe(false);
  });

  it('setTraceId stores trace id', () => {
    useChatStore.getState().setTraceId('trace-abc');
    expect(useChatStore.getState().currentTraceId).toBe('trace-abc');
  });
});
