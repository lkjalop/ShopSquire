import { useEffect, useMemo, useState } from 'react';
import styles from './CartPanel.module.css';
import type { Product } from '../App';
import { apiUrl, safeJson, confirmCartSourcing } from '../lib/api';
import { productDisplayName, productSubtitle } from '../lib/productDisplay';

type CartItem = { sku: string; quantity: number; price_cents?: number; name?: string; specs?: Record<string, any> | null };
type BundleSavings = {
  status?: string;
  message?: string;
  subtotal_cents?: number;
  laptop_subtotal_cents?: number;
  accessories_subtotal_cents?: number;
  discount_cents?: number;
  applied_discount_cents?: number;
  final_total_cents?: number;
  estimated_final_total_cents?: number;
  amount_to_next_cents?: number;
  approval_required?: boolean;
  approval_badge?: string | null;
  approval_id?: string | null;
};
type CartState = { cart_id: string; items: CartItem[]; subtotal_cents: number; currency: string; bundle_savings?: BundleSavings };

export default function CartPanel({
  uid,
  cart,
  onRefresh,
  onRemove,
  onClear,
  onAdd,
  onSetQty,
  onTraceId,
}: {
  uid: string;
  cart: CartState | null;
  onRefresh: () => Promise<void>;
  onRemove: (sku: string) => Promise<void>;
  onClear: () => Promise<void>;
  onAdd: (sku: string) => Promise<void>;
  onSetQty?: (sku: string, qty: number) => Promise<void>;
  onTraceId?: (traceId: string | null) => void;
}) {
  const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
  const [upsells, setUpsells] = useState<Product[]>([]);
  const [upsellTraceId, setUpsellTraceId] = useState<string | null>(null);
  const [loadingUpsell, setLoadingUpsell] = useState(false);

  const cartSkus = useMemo(() => (cart?.items || []).map((i) => i.sku).filter(Boolean), [cart]);
  const upsellQuery = useMemo(() => {
    if (!cartSkus.length) return null;
    if (cartSkus.length === 1) return `Recommend 4 complementary alternatives to ${cartSkus[0]} under similar budget.`;
    return `Recommend 4 complementary alternatives for a cart containing: ${cartSkus.slice(0, 4).join(', ')}.`;
  }, [cartSkus]);

  useEffect(() => {
    let mounted = true;
    const fetchUpsell = async () => {
      if (!upsellQuery) {
        setUpsells([]);
        setUpsellTraceId(null);
        return;
      }
      setLoadingUpsell(true);
      try {
        const u = new URL(apiUrl('/api/v1/recommend/checkout_upsell'), window.location.href);
        u.searchParams.set('uid', uid || 'demo-user');
        u.searchParams.set('cart_skus', cartSkus.join(','));
        u.searchParams.set('limit', '4');
        const lastQuery = String(localStorage.getItem('shopsquire_last_user_query') || '').trim();
        const lastPersona = String(localStorage.getItem('shopsquire_last_persona') || '').trim();
        const lastUseCase = String(localStorage.getItem('shopsquire_last_use_case') || '').trim();
        if (lastQuery) u.searchParams.set('query', lastQuery);
        if (lastPersona) u.searchParams.set('persona', lastPersona);
        if (lastUseCase) u.searchParams.set('use_case', lastUseCase);
        const r = await fetch(u.toString(), {
          credentials: 'include',
          headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
        });
        const j = await safeJson(r);
        if (!r.ok || !j) throw new Error('upsell_failed');
        const results = (j.results || []) as any[];
        const prods = results.slice(0, 4).map((it) => ({
          sku: it.sku,
          name: it.name,
          price: it.price_cents ? it.price_cents / 100 : (it.price ?? 0),
          features: it.features || [],
          image_url: it.image_url,
          why: (it.reasons || it.factors?.positive || []).slice(0, 3),
          why_codes: (it.reason_codes || []).slice(0, 3),
          why_confidence: it.reason_confidence,
          model_source: it.model_source,
          score_norm: it.score_norm,
        })) as Product[];
        const tid = j.decision_trace_id || j.trace_id || j.decision_id || null;
        if (mounted) {
          setUpsells(prods);
          setUpsellTraceId(tid);
        }
      } catch {
        if (mounted) {
          setUpsells([]);
          setUpsellTraceId(null);
        }
      } finally {
        if (mounted) setLoadingUpsell(false);
      }
    };
    fetchUpsell();
    return () => {
      mounted = false;
    };
  }, [API_KEY, uid, upsellQuery, cartSkus]);

  useEffect(() => {
    onTraceId?.(upsellTraceId);
  }, [upsellTraceId, onTraceId]);

  const items = cart?.items || [];
  const bundle = cart?.bundle_savings;
  const [sourcingNote, setSourcingNote] = useState<string | null>(null);
  const [checkingSourcing, setCheckingSourcing] = useState(false);

  const proceedToCheckout = () => {
    // Persist cart snapshot so the checkout page can show an order summary
    try {
      sessionStorage.setItem('shopsquire_checkout_cart', JSON.stringify(cart));
    } catch {
      // sessionStorage unavailable — continue anyway
    }
    window.location.href = '/ui/checkout';
  };
  // Bridge: at checkout, route any SHORT-STOCK cart lines to sourcing (GATE 1). In-stock lines create no
  // case; idempotent on cart_id; rate-limited server-side; best-effort (never blocks checkout). When a
  // sourcing request is created we pause so the buyer sees it, then they proceed to checkout for the rest.
  const goToCheckout = async () => {
    setCheckingSourcing(true);
    try {
      if (cart?.cart_id && items.length) {
        const res = await confirmCartSourcing(uid, cart.cart_id,
          items.map((i) => ({ item_ref: i.sku, quantity: i.quantity })));
        if ((res.case_count ?? 0) > 0) {
          setSourcingNote(`${res.case_count} item group(s) are short on stock — a sourcing request was created (no supplier contacted yet). In-stock items can check out now.`);
          setCheckingSourcing(false);
          return;
        }
      }
    } catch {
      // sourcing is best-effort — fall through to normal checkout
    }
    setCheckingSourcing(false);
    proceedToCheckout();
  };
  const openApprovalReview = () => {
    const approvalId = String(bundle?.approval_id || '').trim();
    const url = new URL('/admin', window.location.origin);
    url.searchParams.set('tab', 'approvals');
    if (approvalId) url.searchParams.set('approval_id', approvalId);
    window.open(url.toString(), '_blank', 'noopener,noreferrer');
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.headerBlock}>
        <div className={styles.sectionTitle}>Your Cart</div>
        {items.length > 0 && (
          <div className={styles.muted}>{items.length} item{items.length !== 1 ? 's' : ''}</div>
        )}
      </div>

      {items.length === 0 ? (
        <div className={styles.muted}>Cart is empty. Add a product to see upsell suggestions.</div>
      ) : (
        <>
          {bundle && (
            <div className={styles.bundleCard}>
              <div className={styles.bundleHeader}>
                <div className={styles.sectionTitle}>Bundle Savings</div>
                {bundle.approval_badge && (
                  <span className={bundle.approval_required ? styles.pendingBadge : styles.appliedBadge}>
                    {bundle.approval_badge}
                  </span>
                )}
              </div>
              <div className={styles.bundleMessage}>{bundle.message || 'Bundle pricing is available for laptop + accessory carts.'}</div>
              <div className={styles.bundleRows}>
                <div className={styles.summaryLine}><span>Laptop price</span><span>${(((bundle.laptop_subtotal_cents || 0) / 100)).toLocaleString()}</span></div>
                <div className={styles.summaryLine}><span>Accessories</span><span>${(((bundle.accessories_subtotal_cents || 0) / 100)).toLocaleString()}</span></div>
                <div className={styles.summaryLine}>
                  <span>{bundle.approval_required ? 'Bundle discount (pending review)' : 'Bundle discount (laptop only)'}</span>
                  <span>- ${((((bundle.approval_required ? bundle.discount_cents : (bundle.applied_discount_cents || bundle.discount_cents)) || 0) / 100)).toLocaleString()}</span>
                </div>
                <div className={`${styles.summaryLine} ${styles.summaryTotal}`}>
                  <span>{bundle.approval_required ? 'Current total' : 'Final total'}</span>
                  <span>${((((bundle.final_total_cents || cart?.subtotal_cents || 0) / 100)).toLocaleString())}</span>
                </div>
                {bundle.approval_required && (
                  <div className={styles.summaryLine}>
                    <span>Estimated total after approval</span>
                    <span>${((((bundle.estimated_final_total_cents || 0) / 100)).toLocaleString())}</span>
                  </div>
                )}
                {bundle.approval_id && (
                  <div className={styles.summaryLine}>
                    <span>Approval ID</span>
                    <span>{bundle.approval_id}</span>
                  </div>
                )}
                {bundle.approval_required && (
                  <div className={styles.btnRow}>
                    <button className={styles.btn} onClick={openApprovalReview}>Open reviewer queue</button>
                  </div>
                )}
              </div>
            </div>
          )}
          {items.map((it) => (
            <div key={it.sku} className={styles.row}>
              <div className={styles.rowLeft}>
                <div className={styles.name}>{productDisplayName(it)}</div>
                {productSubtitle(it) && <div className={styles.sku}>{productSubtitle(it)}</div>}
                <div className={styles.sku}>{it.sku}</div>
                {onSetQty ? (
                  <div className={styles.qty} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span>Qty:</span>
                    <button type="button" aria-label={`decrease ${it.sku}`} className={styles.btn}
                            disabled={it.quantity <= 1}
                            onClick={() => onSetQty(it.sku, it.quantity - 1)}>−</button>
                    <span data-testid={`qty-${it.sku}`}>{it.quantity}</span>
                    <button type="button" aria-label={`increase ${it.sku}`} className={styles.btn}
                            onClick={() => onSetQty(it.sku, it.quantity + 1)}>＋</button>
                  </div>
                ) : (
                  <div className={styles.qty}>Qty: {it.quantity}</div>
                )}
              </div>
              <div className={styles.rowRight}>
                <div className={styles.price}>
                  {typeof it.price_cents === 'number' ? `$${(it.price_cents / 100).toLocaleString()}` : '-'}
                </div>
                <div className={styles.btnRow}>
                  <button className={styles.btn} onClick={() => onRemove(it.sku)}>Remove</button>
                </div>
              </div>
            </div>
          ))}

          <div className={styles.row}>
            <div className={styles.rowLeft}>
              <div className={styles.name}>Subtotal</div>
              <div className={styles.muted}>{cart?.currency || 'USD'}</div>
            </div>
            <div className={styles.rowRight}>
              <div className={styles.price}>${(((bundle?.final_total_cents ?? cart?.subtotal_cents ?? 0) / 100)).toLocaleString()}</div>
              <div className={styles.btnRow}>
                <button className={styles.btn} onClick={() => onRefresh()}>Refresh</button>
                <button className={styles.btn} onClick={() => onClear()}>Clear</button>
                {sourcingNote
                  ? <button className={`${styles.btn} ${styles.btnPrimary}`} data-testid="cart-proceed"
                            onClick={proceedToCheckout}>Continue to checkout</button>
                  : <button className={`${styles.btn} ${styles.btnPrimary}`} data-testid="cart-checkout"
                            disabled={checkingSourcing} onClick={goToCheckout}>
                      {checkingSourcing ? 'Checking stock…' : 'Checkout'}
                    </button>}
              </div>
            </div>
          </div>
          {sourcingNote && (
            <div data-testid="cart-sourcing-note" role="status"
                 style={{ margin: '8px 0', padding: '8px 10px', borderRadius: 8, border: '1px solid #fcd34d',
                          background: '#fffbeb', fontSize: 13 }}>
              {sourcingNote}
            </div>
          )}
        </>
      )}

      <div className={styles.upsellSection}>
        <div className={styles.sectionTitle}>Recommended Add-Ons</div>
        {loadingUpsell && <div className={styles.muted}>Loading suggestions...</div>}
        {!loadingUpsell && upsells.length === 0 && (
          <div className={styles.muted}>
            No compatible add-ons found right now. We avoid showing unrelated products.
          </div>
        )}

        {!loadingUpsell && upsells.length > 0 && (
          <>
            <div className={styles.upsellList}>
              {upsells.map((p) => (
                <div key={p.sku} className={styles.row}>
                  <div className={styles.rowLeft}>
                    <div className={styles.name}>{productDisplayName(p)}</div>
                    {productSubtitle(p) && <div className={styles.sku}>{productSubtitle(p)}</div>}
                    <div className={styles.sku}>{p.sku}</div>
                    {(p.why && p.why.length > 0) && (
                      <div className={styles.pillRow}>
                        {p.why.slice(0, 3).map((w, idx) => <span key={idx} className={styles.pill}>{w}</span>)}
                      </div>
                    )}
                    {(p.why_codes && p.why_codes.length > 0) && (
                      <div className={styles.pillRow}>
                        {p.why_codes.slice(0, 2).map((w, idx) => (
                          <span key={`code-${idx}`} className={styles.pill}>
                            {w.label || w.code || 'reason'} ({Math.round((w.confidence || 0) * 100)}%)
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className={styles.rowRight}>
                    <div className={styles.price}>${(p.price || 0).toLocaleString()}</div>
                    {typeof p.why_confidence === 'number' && (
                      <div className={styles.sku}>Confidence: {Math.round((p.why_confidence || 0) * 100)}%</div>
                    )}
                    <div className={styles.btnRow}>
                      <button className={styles.btn} onClick={() => onAdd(p.sku)}>Add</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className={styles.bottomCarousel} aria-label="cart-bottom-carousel">
              <div className={styles.carouselTitle}>Quick Add Carousel</div>
              <div className={styles.carouselTrack}>
                {upsells.map((p) => (
                  <article key={`carousel-${p.sku}`} className={styles.carouselCard}>
                    <div className={styles.carouselName}>{p.name}</div>
                    <div className={styles.sku}>{p.sku}</div>
                    {(p.why && p.why.length > 0) && (
                      <div className={styles.pillRow}>
                        {p.why.slice(0, 2).map((w, idx) => <span key={`carousel-why-${idx}`} className={styles.pill}>Why: {w}</span>)}
                      </div>
                    )}
                    {(p.why_codes && p.why_codes.length > 0) && (
                      <div className={styles.pillRow}>
                        {p.why_codes.slice(0, 1).map((w, idx) => (
                          <span key={`carousel-code-${idx}`} className={styles.pill}>
                            {w.code} {Math.round((w.confidence || 0) * 100)}%
                          </span>
                        ))}
                      </div>
                    )}
                    <div className={styles.carouselMeta}>
                      <span className={styles.price}>${(p.price || 0).toLocaleString()}</span>
                      <button className={`${styles.btn} ${styles.carouselAddBtn}`} onClick={() => onAdd(p.sku)}>
                        Add
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {upsellTraceId && (
        <div className={styles.muted}>
          Decision Trace available: <span className={styles.sku}>{upsellTraceId}</span>
        </div>
      )}
    </div>
  );
}
