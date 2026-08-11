import { useEffect, useState } from 'react';
import { getSplitOffer, type SplitPlan } from '../lib/api';

// Pre-payment split-fulfilment disclosure. When a bulk cart exceeds on-hand stock, ShopSquire does NOT
// silently backorder — it shows the buyer exactly what ships now (from stock) and what follows from a
// supplier, with the SUPPLIER's own lead time as the ETA (a real figure, not a guess), plus the store's
// delivery economics (fees / free-shipping threshold from the StoreProfile). The buyer CONFIRMS this plan
// before payment; the parent gates checkout on that confirmation.
export default function SplitFulfillmentCard({
  uid,
  refreshKey,
  nameFor,
  onSplitState,
  onConfirmed,
}: {
  uid: string;
  refreshKey: string;                                   // re-fetch when the cart signature changes
  nameFor: (sku: string) => string;                     // resolve a display name from the cart
  onSplitState?: (hasSplit: boolean, confirmed: boolean) => void;
  onConfirmed?: () => boolean | void | Promise<boolean | void>;
}) {
  const [plan, setPlan] = useState<SplitPlan | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let alive = true;
    setConfirmed(false);
    onSplitState?.(false, false);
    if (!refreshKey) { setPlan(null); return; }
    getSplitOffer(uid)
      .then((res) => {
        if (!alive) return;
        setPlan(res.split);
        const hasSplit = !!(res.split && !res.split.fully_in_stock);
        onSplitState?.(hasSplit, false);
      })
      .catch(() => { if (alive) { setPlan(null); onSplitState?.(false, false); } });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, refreshKey]);

  // Only surface when there IS a supplier-backed second shipment to disclose (the pre-payment beat). A
  // fully-in-stock cart ships in one go — no split card, no extra confirmation.
  if (!plan || (plan.fully_in_stock && !plan.transfers?.length)) return null;

  const d = plan.delivery;
  const money = (c: number) => `$${(c / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const confirmPlan = async () => {
    if (confirming) return;
    setConfirming(true);
    try {
      const accepted = await onConfirmed?.();
      if (accepted === false) return;
      setConfirmed(true);
      onSplitState?.(true, true);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div
      data-testid="split-fulfillment-card"
      style={{
        margin: '10px 0', padding: '12px 14px', borderRadius: 10,
        border: '1px solid #93c5fd', background: '#eff6ff', fontSize: 13,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>Delivery plan — confirm before payment</div>
      <div data-testid="split-rationale" style={{ color: '#1e3a8a', marginBottom: 10 }}>{plan.rationale}</div>

      <div style={{ fontWeight: 600, color: '#065f46', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.4 }}>
        Ships now — in stock
      </div>
      {plan.now.map((l) => (
        <div key={`now-${l.sku}`} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
          <span>{l.qty} × {nameFor(l.sku)}</span>
          <span style={{ color: '#6b7280' }}>{l.sku}</span>
        </div>
      ))}

      {!!plan.transfers?.length && (
        <>
          <div style={{ fontWeight: 600, color: '#1d4ed8', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 8 }}>
            Transfers from our network
          </div>
          {plan.transfers.map((l) => (
            <div key={`transfer-${l.sku}`} data-testid={`split-transfer-${l.sku}`}
                 style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
              <span>{l.qty} × {nameFor(l.sku)}</span>
              <span style={{ color: '#1d4ed8' }}>confirmed internal stock</span>
            </div>
          ))}
        </>
      )}

      {!!plan.later?.length && (
        <>
          <div style={{ fontWeight: 600, color: '#92400e', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 8 }}>
            Requires supplier RFQ
          </div>
          {plan.later.map((l) => (
            <div key={`later-${l.sku}`} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
              <span>{l.qty} × {nameFor(l.sku)}</span>
              <span style={{ color: '#92400e' }} data-testid={`split-eta-${l.sku}`}>
                {l.eta_days != null ? `supplier lead time ~${l.eta_days} days` : 'availability unconfirmed'}
                {l.supplier_ref ? ` · ${l.supplier_ref}` : ''}
              </span>
            </div>
          ))}
        </>
      )}

      <div data-testid="split-delivery" style={{ marginTop: 10, paddingTop: 8, borderTop: '1px dashed #93c5fd', color: '#1e3a8a' }}>
        {d.waived
          ? `Free delivery — order over ${money(d.free_shipping_threshold_cents)} (${d.shipments} shipment${d.shipments !== 1 ? 's' : ''}, no fee)`
          : `Delivery: ${money(d.fee_now_cents)} now + ${money(d.fee_later_cents)} on the follow-up shipment (${d.shipments} shipments)`}
      </div>

      <div style={{ marginTop: 10 }}>
        {plan.fully_in_stock ? (
          <div data-testid="split-network-covered" style={{ color: '#065f46', fontWeight: 600 }}>
            Covered by confirmed internal inventory — no supplier RFQ required.
          </div>
        ) : confirmed ? (
          <div data-testid="split-confirmed" style={{ color: '#065f46', fontWeight: 600 }}>
            ✓ Delivery plan confirmed — you can check out.
          </div>
        ) : (
          <button
            type="button"
            data-testid="split-confirm"
            onClick={() => { void confirmPlan(); }}
            disabled={confirming}
            style={{
              padding: '7px 14px', borderRadius: 8, border: 'none', cursor: confirming ? 'wait' : 'pointer',
              background: '#2563eb', color: '#fff', fontWeight: 600, fontSize: 13,
            }}
          >
            {confirming ? 'Confirming delivery plan…' : 'Confirm delivery plan'}
          </button>
        )}
      </div>
    </div>
  );
}
