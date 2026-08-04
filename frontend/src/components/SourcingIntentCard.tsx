/**
 * SourcingIntentCard — the buyer side of FLUID procurement (FULFILLMENT_DEFER_TO_CART).
 *
 * When a query needs sourcing, the backend returns a buyer-safe `sourcing_intent` PREVIEW (no durable case,
 * no supplier contacted). This card makes that preview visible — "needs confirmation before sourcing" — and
 * gives the buyer a single GATE-1 action: "Confirm sourcing from cart", which POSTs to
 * /api/v1/fulfillment/cases/confirm-cart and materializes one durable case per supplier group, idempotently.
 *
 * Honest copy: nothing is ordered and no supplier is contacted until the buyer confirms. Supplier identity
 * stays server-side (the preview never names a supplier).
 */
import { useState } from 'react';
import { commitFulfillmentCase, confirmCartSourcing, type ConfirmCartResult, type SourcingIntent } from '../lib/api';

interface Props {
  intent: SourcingIntent;
  uid: string;
  orderId: string;        // commitment reference / idempotency key (the turn's trace id is stable + fine)
  traceId?: string;
  onConfirmed?: (r: ConfirmCartResult) => void;
}

export default function SourcingIntentCard({ intent, uid, orderId, traceId, onConfirmed }: Props) {
  const [result, setResult] = useState<ConfirmCartResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lines = intent.lines || [];
  const unresolved = intent.unresolved_phrases || [];
  const totalUnits = lines.reduce((n, l) => n + (Number(l.quantity) || 0), 0);

  const run = async (supersede: boolean) => {
    setBusy(true); setError('');
    try {
      const r = await confirmCartSourcing(uid, orderId, lines, traceId, supersede, intent.requirements);
      let out = r;
      if (!supersede && !r.idempotent && !r.amend_required && r.status == null && Array.isArray(r.cases) && r.cases.length > 0) {
        let committed = 0;
        for (const c of r.cases) {
          if (c?.case_id) {
            await commitFulfillmentCase(c.case_id, uid);
            committed += 1;
          }
        }
        out = { ...r, committed_count: committed } as ConfirmCartResult;
      }
      setResult(out);
      onConfirmed?.(out);
    } catch (e: any) {
      setError(e?.message || 'could not confirm sourcing');
    } finally {
      setBusy(false);
    }
  };
  const onConfirm = () => run(false);
  const onSupersede = () => run(true);

  return (
    <section data-testid="sourcing-intent" className="fulfilment-options" aria-label="Sourcing preview">
      <header>
        <strong>Sourcing preview</strong>{' '}
        <span data-testid="si-status">needs confirmation before sourcing</span>
      </header>

      <ol className="fc-why" data-testid="si-lines">
        {lines.map((l, i) => (
          <li key={`${l.item_ref}-${i}`}>
            <strong>{l.name || l.item_ref}</strong>{l.name ? <span style={{ color: '#6b7280' }}> ({l.item_ref})</span> : null} — {l.quantity} unit(s)
            {l.shortfall != null && l.shortfall !== l.quantity ? ` (${l.shortfall} to source)` : ''}
          </li>
        ))}
      </ol>
      <p>
        Preview only — {lines.length} item line(s), {totalUnits} unit(s)
        {intent.planned_case_count ? `, ~${intent.planned_case_count} supplier request(s)` : ''}.
        Nothing is ordered and no supplier is contacted until you confirm.
      </p>

      {/* phrases we couldn't match to a product — surfaced, never silently dropped. Confirm is blocked until
          they're resolved so the buyer never gets fewer items than they asked for. */}
      {unresolved.length > 0 && (
        <div data-testid="si-unresolved" role="status" style={{ color: '#b45309' }}>
          We couldn't match {unresolved.length} item(s) you asked for:{' '}
          {unresolved.map((u, i) => (
            <span key={i}>{i > 0 ? ', ' : ''}{u.quantity ?? '?'}× “{u.phrase ?? 'unknown'}”</span>
          ))}. Please tell us which product you mean before confirming, so nothing is missed.
        </div>
      )}

      {error && <p role="alert" data-testid="si-error">{error}</p>}

      {!result && (
        <button disabled={busy || unresolved.length > 0} onClick={onConfirm} data-testid="si-confirm-btn"
                title={unresolved.length > 0 ? 'Resolve the unmatched items before confirming' : undefined}>
          {busy ? 'Confirming…' : 'Confirm sourcing from cart'}
        </button>
      )}

      {/* amendment after a confirmed order: offer the deliberate supersede action (retire old + re-source) */}
      {result && result.amend_required && (
        <div data-testid="si-amend">
          <p role="status">
            This order was already confirmed with different items. Nothing was duplicated. You can supersede
            the earlier request and re-source the new items.
          </p>
          <button disabled={busy} onClick={onSupersede} data-testid="si-supersede-btn">
            {busy ? 'Updating…' : 'Supersede & re-source'}
          </button>
        </div>
      )}

      {/* supersede outcome */}
      {result && result.status === 'superseded' && (
        <p data-testid="si-superseded" role="status">
          Updated — retired {result.superseded?.length ?? 0} earlier request(s) and created
          {' '}{result.created?.case_count ?? 0} new one(s). No supplier was contacted.
        </p>
      )}
      {result && result.status === 'operator_required' && (
        <p data-testid="si-operator" role="status">
          A supplier has already been contacted for the earlier request, so our team will handle this
          change directly. Nothing was duplicated.
        </p>
      )}

      {/* first-confirm outcome (materialize) */}
      {result && !result.amend_required && result.status == null && (
        <p data-testid="si-created" role="status">
          {(result.case_count ?? 0) > 0
            ? `Created ${result.case_count} sourcing request(s)${result.idempotent ? ' (already confirmed earlier)' : ''} — the procurement team has been notified. No supplier has been contacted yet.`
            : 'Everything is available from stock — no sourcing was needed.'}
        </p>
      )}
    </section>
  );
}
