/**
 * src/store/index.ts — Zustand global state stores for ShopSquire.
 *
 * Three slices:
 *   cartStore   — shopping cart contents + actions
 *   authStore   — current user auth state
 *   chatStore   — chat overlay messages + UI state
 */
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// ── Types ──────────────────────────────────────────────────────────────────

export interface CartItem {
  sku: string;
  name?: string;
  quantity: number;
  price_cents?: number;
}

export interface CartState {
  cart_id: string;
  items: CartItem[];
  subtotal_cents: number;
  currency: string;
}

export interface AuthUser {
  uid: string;
  role: string;
  email?: string;
}

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  traceId?: string;
  timestamp: number;
}

// ── Cart store ─────────────────────────────────────────────────────────────

interface CartSlice {
  cart: CartState | null;
  loading: boolean;
  error: string | null;
  setCart: (cart: CartState | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  optimisticRemove: (sku: string) => void;
  optimisticClear: () => void;
}

export const useCartStore = create<CartSlice>()((set) => ({
  cart: null,
  loading: false,
  error: null,

  setCart: (cart) => set({ cart, error: null }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  optimisticRemove: (sku) =>
    set((state) => {
      if (!state.cart) return state;
      const items = state.cart.items.filter((i) => i.sku !== sku);
      const subtotal_cents = items.reduce(
        (sum, i) => sum + (i.price_cents ?? 0) * i.quantity,
        0
      );
      return { cart: { ...state.cart, items, subtotal_cents } };
    }),

  optimisticClear: () =>
    set((state) => {
      if (!state.cart) return state;
      return { cart: { ...state.cart, items: [], subtotal_cents: 0 } };
    }),
}));

// ── Auth store (persisted to sessionStorage) ───────────────────────────────

interface AuthSlice {
  user: AuthUser | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (user: AuthUser, token: string) => void;
  logout: () => void;
  updateRole: (role: string) => void;
}

export const useAuthStore = create<AuthSlice>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      login: (user, token) => set({ user, token, isAuthenticated: true }),
      logout: () => set({ user: null, token: null, isAuthenticated: false }),
      updateRole: (role) =>
        set((state) => ({
          user: state.user ? { ...state.user, role } : null,
        })),
    }),
    {
      name: 'shopsquire-auth',
      storage: createJSONStorage(() => sessionStorage),
      // Only persist non-sensitive fields
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        // Intentionally NOT persisting token to avoid localStorage XSS risk
      }),
    }
  )
);

// ── Chat store ─────────────────────────────────────────────────────────────

interface ChatSlice {
  messages: ChatMessage[];
  sessionId: string | null;
  isOpen: boolean;
  isLoading: boolean;
  currentTraceId: string | null;
  addMessage: (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => void;
  clearMessages: () => void;
  setSessionId: (sessionId: string | null) => void;
  setOpen: (open: boolean) => void;
  setLoading: (loading: boolean) => void;
  setTraceId: (traceId: string | null) => void;
}

let _msgCounter = 0;

export const useChatStore = create<ChatSlice>()((set) => ({
  messages: [],
  sessionId: null,
  isOpen: false,
  isLoading: false,
  currentTraceId: null,

  addMessage: (msg) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          ...msg,
          id: `msg-${Date.now()}-${++_msgCounter}`,
          timestamp: Date.now(),
        },
      ],
    })),

  clearMessages: () => set({ messages: [] }),
  setSessionId: (sessionId) => set({ sessionId }),
  setOpen: (isOpen) => set({ isOpen }),
  setLoading: (isLoading) => set({ isLoading }),
  setTraceId: (currentTraceId) => set({ currentTraceId }),
}));
