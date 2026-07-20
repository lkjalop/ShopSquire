import { useEffect, useMemo, useRef, useState } from 'react';
import styles from './CartPanel.module.css';
import type { Product } from '../App';
import { apiUrl, safeJson, confirmCartSourcing, commitFulfillmentCase } from '../lib/api';
import { sourcedCasesFrom, sourcedCaseCountFrom } from '../lib/sourcing';
import { withRetry } from '../lib/retry';
import { productDisplayName, productSubtitle } from '../lib/productDisplay';
import SplitFulfillmentCard from './SplitFulfillmentCard';

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
  traceId,
  onTraceId,
  onSourcingTraceId,
  priorSkus,
  onClearPrior,
  sourcingRequirements,
  sourcingOrderId,
}: {
  uid: string;
  cart: CartState | null;
  onRefresh: () => Promise<void>;
  onRemove: (sku: string) => Promise<void>;
  onClear: () => Promise<void>;
  onAdd: (sku: string) => Promise<void>;
  onSetQty?: (sku: string, qty: number) => Promise<void>;
  traceId?: string | null;
  onTraceId?: (traceId: string | null) => void;
  onSourcingTraceId?: (traceId: string) => void;
  priorSkus?: string[];                    // items carried over from a previous session (App snapshots)
  onClearPrior?: () => Promise<void>;      // remove ONLY those, keeping what was added this session
  sourcingRequirements?: Record<string, any>; // deadline/use-case/ship-to from the recommendation turn
  sourcingOrderId?: string | null;             // stable PR identity; cart_id is only a legacy fallback
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
    // Do NOT let the checkout-upsell trace REPLACE the main recommendation/procurement decision trace:
    // the Decision Trace the buyer opens must stay pinned to the laptop/bulk decision, not accessory
    // upsells — otherwise Events / Why-Recommended / the Procurement tab tell the wrong story. Only
    // surface the upsell trace upward when there is NO main trace to preserve (the upsell trace id is
    // still shown inline below regardless).
    if (upsellTraceId && !traceId) onTraceId?.(upsellTraceId);
  }, [upsellTraceId, traceId, onTraceId]);

  const items = cart?.items || [];
  const bundle = cart?.bundle_savings;
  const [sourcingNote, setSourcingNote] = useState<string | null>(null);
  const [checkingSourcing, setCheckingSourcing] = useState(false);
  // Pre-payment split-fulfilment confirmation. The card reports whether the cart splits (a supplier-backed
  // second shipment exists) and whether the buyer has confirmed the plan; checkout is gated on that confirm.
  const [splitHasSplit, setSplitHasSplit] = useState(false);
  const [splitConfirmed, setSplitConfirmed] = useState(false);
  // A stable signature of the cart lines (sku:qty) — the split card re-fetches whenever this changes.
  const splitKey = useMemo(
    () => (cart?.items || []).map((i) => `${i.sku}:${i.quantity}`).sort().join('|'),
    [cart],
  );
  const nameForSku = (sku: string): string => {
    const it = (cart?.items || []).find((x) => x.sku === sku);
    return it ? productDisplayName(it) : sku;
  };
  const onSplitState = (hasSplit: boolean, confirmed: boolean) => {
    setSplitHasSplit(hasSplit);
    setSplitConfirmed(confirmed);
  };
  // The delivery-plan card is the real CTA; the footer "Confirm delivery plan first" is a helper that
  // scrolls to it (rather than a dead disabled button that looks broken).
  const splitCardRef = useRef<HTMLDivElement>(null);
  const scrollToPlan = () => splitCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  // Confirm sourcing for the CURRENT cart, transparently SUPERSEDING when the cart CHANGED since a prior
  // confirm of this same order. Without this the backend returns `amend_required` + the STALE cases (the
  // previous order's SKUs/qty), and the Procurement tab would open the OLD RFQ — the wrong story for a
  // demo. On amend we re-source with supersede=true so the returned (nested `created`) cases match the
  // current cart. Returns null when a supplier was already engaged (past the send gate) — that is an
  // operator-driven amendment and must not be auto-superseded.
  const sourceCurrentCart = async () => {
    const cid = sourcingOrderId || cart?.cart_id;
    if (!cid) return null;
    // Pass the current decision trace so the sourcing case records source_trace_id — the Decision Trace
    // → Procurement tab resolves the drafted RFQ by-trace (was null → 404 → empty tab).
    const lines = items.map((i) => ({ item_ref: i.sku, quantity: i.quantity }));
    let res = await confirmCartSourcing(uid, cid, lines, traceId || undefined, false, sourcingRequirements);
    if (res.amend_required) {
      res = await confirmCartSourcing(uid, cid, lines, traceId || undefined, true, sourcingRequirements);
    }
    return res.status === 'operator_required' ? null : res;
  };
  // GATE 1 on "Confirm delivery plan": committing the plan IS the buyer commitment — it creates the
  // sourcing cases and auto-drafts the supplier RFQs (human-gated, never sent). Payment capture is a
  // LATER, PCI-gated step — a demo can show the drafted RFQ without ever touching payment credentials.
  const confirmPlanSourcing = async () => {
    try {
      if (!cart?.cart_id || !items.length) return;
      const res = await sourceCurrentCart();
      if (!res) {
        setSourcingNote('This order changed after a supplier was already engaged — an operator must amend it. Nothing was re-sent.');
        return;
      }
      const cases = sourcedCasesFrom(res);
      const caseCount = sourcedCaseCountFrom(res);
      if (traceId && caseCount > 0) onSourcingTraceId?.(traceId);
      if (res.idempotent) {
        setSourcingNote(`${caseCount} sourcing request(s) were already confirmed earlier. No duplicate RFQ was created; open the original case in Admin to review its draft and audit.`);
        return;
      }
      let committed = 0;
      for (const c of cases) {
        // retry once: a multi-case commit burst can hit a transient write lock — without the retry one
        // supplier's case silently stays uncommitted and its RFQ is never drafted (observed live).
        try {
          await withRetry(() => commitFulfillmentCase((c as any).case_id, uid));
          committed += 1;
        } catch {
          // Report the partial failure below. The case remains visible in the operator queue for retry.
        }
      }
      if (committed === caseCount && caseCount > 0) {
        setSourcingNote(`${caseCount} sourcing request(s) committed — supplier RFQ(s) drafted for human review (nothing sent). Open Decision Trace → Procurement to see the drafts + audit.`);
        // Do NOT overwrite the decision trace id with order_group_id here: the Procurement tab resolves
        // the case via /cases/by-trace/{source_trace_id}; traceId already IS that trace.
      } else if (caseCount > 0) {
        setSourcingNote(`${committed} of ${caseCount} sourcing request(s) committed. The remaining case(s) need operator retry; no draft is claimed for them.`);
      }
    } catch {
      setSourcingNote('The delivery plan was confirmed, but sourcing could not be recorded. Retry or ask an operator; no supplier message was sent.');
    }
  };
  const splitBlocksCheckout = splitHasSplit && !splitConfirmed;

  const proceedToCheckout = () => {
    // Persist cart snapshot (+ uid, so checkout can create the REAL order server-side)
    try {
      sessionStorage.setItem('shopsquire_checkout_cart', JSON.stringify({ ...cart, uid }));
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
        const res = await sourceCurrentCart();  // amend-aware: supersedes stale cases if the cart changed
        if (!res) {
          setSourcingNote('This order changed after a supplier was already engaged — an operator must amend it before checkout.');
          setCheckingSourcing(false);
          return;
        }
        const caseCount = sourcedCaseCountFrom(res);
        if (caseCount > 0) {
          setSourcingNote(`${caseCount} item group(s) are short on stock — a sourcing request was created (no supplier contacted yet). In-stock items can check out now.`);
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
                {typeof it.price_cents === 'number' ? (
                  <div className={styles.price} data-testid={`line-price-${it.sku}`}>
                    {it.quantity > 1 ? (
                      <>
                        <span style={{ color: '#6b7280', fontSize: 12, fontWeight: 400 }}>
                          {it.quantity} × ${(it.price_cents / 100).toLocaleString()} = </span>
                        ${((it.price_cents * it.quantity) / 100).toLocaleString()}
                      </>
                    ) : `$${(it.price_cents / 100).toLocaleString()}`}
                  </div>
                ) : (
                  <div className={styles.price}>-</div>
                )}
                <div className={styles.btnRow}>
                  <button className={styles.btn} onClick={() => onRemove(it.sku)}>Remove</button>
                </div>
              </div>
            </div>
          ))}

          <div ref={splitCardRef}>
            <SplitFulfillmentCard uid={uid} refreshKey={splitKey} nameFor={nameForSku} onSplitState={onSplitState}
                                  onConfirmed={confirmPlanSourcing} />
          </div>

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
                {(priorSkus?.length ?? 0) > 0 && onClearPrior && (
                  // the two-choice clear: drop ONLY the items carried over from a previous session,
                  // keeping everything the buyer added this session
                  <button className={styles.btn} data-testid="cart-clear-prior" onClick={() => onClearPrior()}
                          title="Remove only the items carried over from your previous session — keeps what you added just now">
                    Clear previous ({priorSkus!.length})
                  </button>
                )}
                {sourcingNote
                  ? <button className={`${styles.btn} ${styles.btnPrimary}`} data-testid="cart-proceed"
                            onClick={proceedToCheckout}>Continue to checkout</button>
                  : splitBlocksCheckout
                    // NOT the primary CTA and NOT a dead disabled button — a secondary helper that jumps to
                    // the real "Confirm delivery plan" control above so the buyer knows what to do next.
                    ? <button className={styles.btn} data-testid="cart-confirm-plan-first" onClick={scrollToPlan}
                              title="Jump to the delivery plan above and confirm it to unlock checkout">
                        ↑ Confirm delivery plan first
                      </button>
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
