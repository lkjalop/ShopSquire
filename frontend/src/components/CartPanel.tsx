import { useEffect, useMemo, useState } from 'react';
import styles from './CartPanel.module.css';
import type { Product } from '../App';
import { apiUrl, safeJson } from '../lib/api';

type CartItem = { sku: string; quantity: number; price_cents?: number; name?: string };
type CartState = { cart_id: string; items: CartItem[]; subtotal_cents: number; currency: string };

export default function CartPanel({
  uid,
  cart,
  onRefresh,
  onRemove,
  onClear,
  onAdd,
  onTraceId,
}: {
  uid: string;
  cart: CartState | null;
  onRefresh: () => Promise<void>;
  onRemove: (sku: string) => Promise<void>;
  onClear: () => Promise<void>;
  onAdd: (sku: string) => Promise<void>;
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
  const goToCheckout = () => {
    // Persist cart snapshot so the checkout page can show an order summary
    try {
      sessionStorage.setItem('shopsquire_checkout_cart', JSON.stringify(cart));
    } catch {
      // sessionStorage unavailable — continue anyway
    }
    window.location.href = '/ui/checkout';
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
          {items.map((it) => (
            <div key={it.sku} className={styles.row}>
              <div className={styles.rowLeft}>
                <div className={styles.name}>{it.name || it.sku}</div>
                <div className={styles.sku}>{it.sku}</div>
                <div className={styles.qty}>Qty: {it.quantity}</div>
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
              <div className={styles.price}>${((cart?.subtotal_cents || 0) / 100).toLocaleString()}</div>
              <div className={styles.btnRow}>
                <button className={styles.btn} onClick={() => onRefresh()}>Refresh</button>
                <button className={styles.btn} onClick={() => onClear()}>Clear</button>
                <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={goToCheckout}>Checkout</button>
              </div>
            </div>
          </div>
        </>
      )}

      <div className={styles.upsellSection}>
        <div className={styles.sectionTitle}>Recommended Add-Ons</div>
        {loadingUpsell && <div className={styles.muted}>Loading suggestions...</div>}
        {!loadingUpsell && upsells.length === 0 && <div className={styles.muted}>No suggestions yet.</div>}

        {!loadingUpsell && upsells.length > 0 && (
          <>
            <div className={styles.upsellList}>
              {upsells.map((p) => (
                <div key={p.sku} className={styles.row}>
                  <div className={styles.rowLeft}>
                    <div className={styles.name}>{p.name}</div>
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
