/**
 * MultiIntentCard — the buyer-facing surface for the P0 multi-intent planner.
 *
 * A mixed turn ("nah too expensive, actually 15 instead, and what headsets + hard drives for $1200 for
 * those?") comes back on the chat response as `multi_intent`: the planner AMENDS the chosen item's qty and
 * SCOPES new-category lines to a budget, then RE-CHECKS the plan adversarially. This card renders that plan
 * so the buyer CONFIRMS each money/qty change — the platform never silently applies it (the whole "AI
 * proposes, human confirms on money/qty" principle). Renders nothing when there's nothing actionable.
 */
import type { MultiIntentPlan, MultiIntentPickResult } from '../lib/api';

function priceText(r: MultiIntentPickResult): string {
  const v = Number(r.price) > 0 ? Number(r.price) : (Number(r.price_cents) > 0 ? Number(r.price_cents) / 100 : 0);
  return v > 0 ? `$${v.toLocaleString()}` : '';
}

export default function MultiIntentCard({ plan, onAmendQty, onAddItem, onDismiss }: {
  plan: MultiIntentPlan;
  onAmendQty: (sku: string, qty: number) => void;
  onAddItem: (sku: string, qty: number) => void;
  onDismiss: () => void;
}) {
  const lines = plan?.plan || [];
  // Only show rows for lines THIS turn actually changed (amended === true) — never for a carried-forward
  // unchanged prior line (a spurious confirm that changes an item the buyer didn't ask about). qty >= 1 is
  // a quantity change; qty === 0 is an explicit REMOVAL row ("get rid of the HP Envy") — still confirmed
  // by a click, never silently applied.
  const amendments = lines.filter(
    (l) => l.scope === 'prior' && l.ref && l.amended === true && typeof l.requested_qty === 'number' && (l.requested_qty as number) >= 1,
  );
  const removals = lines.filter(
    (l) => l.scope === 'prior' && l.ref && l.amended === true && typeof l.requested_qty === 'number' && (l.requested_qty as number) === 0,
  );
  const newLines = lines.filter((l) => l.scope === 'new');
  const hasNewPicks = newLines.some((l) => (l.results?.length ?? 0) > 0);
  const actionable = amendments.length + removals.length;
  // Nothing to confirm → render nothing (a plain single-intent turn never reaches here anyway).
  if (!actionable && !hasNewPicks) return null;
  const applyAll = async () => {
    // one click applies every line-op in the plan (removals first, then qty changes) — each is still an
    // explicit cart API call; the plan itself was human-reviewed on this card.
    for (const l of [...removals, ...amendments]) {
      await onAmendQty(l.ref as string, l.requested_qty as number);
    }
  };

  return (
    <section data-testid="multi-intent-card"
             style={{ border: '1px solid #c7d2fe', background: '#eef2ff', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ fontWeight: 700, color: '#3730a3', marginBottom: 6 }}>
        I caught a few things in that — confirm before I change your cart:
      </div>
      {plan.objection_angle === 'value' && (
        <div data-testid="multi-intent-objection" style={{ fontSize: 13, color: '#166534', marginBottom: 8 }}>
          💰 You mentioned budget — these picks lead on value, not just sticker price.
        </div>
      )}

      {/* explicit removals ("get rid of the HP Envy") — confirmed by click, executed as qty-0 */}
      {removals.map((l) => (
        <div key={`rm-${l.ref}`} data-testid={`multi-intent-remove-${l.ref}`}
             style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '4px 0' }}>
          <span style={{ fontSize: 14 }}>
            Remove <strong>{l.name || l.ref}</strong> from the cart
          </span>
          <button onClick={() => onAmendQty(l.ref as string, 0)}
                  style={{ background: '#dc2626', color: '#fff', border: 'none', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontWeight: 600 }}>
            Remove
          </button>
        </div>
      ))}

      {/* qty amendment on the already-chosen item — confirm, never auto-apply */}
      {amendments.map((l) => (
        <div key={l.ref} data-testid={`multi-intent-amend-${l.ref}`}
             style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '4px 0' }}>
          <span style={{ fontSize: 14 }}>
            {plan.quantity_expression === 'approximate' ? (
              <>You said about <strong>{l.requested_qty}</strong> for <strong>{l.name || l.ref}</strong>. Set it to exactly <strong>{l.requested_qty}</strong>?</>
            ) : (
              <>Change <strong>{l.name || l.ref}</strong> quantity to <strong>{l.requested_qty}</strong></>
            )}
          </span>
          <button onClick={() => onAmendQty(l.ref as string, l.requested_qty as number)}
                  style={{ background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontWeight: 600 }}>
            Confirm qty
          </button>
        </div>
      ))}
      {amendments.length > 0 && (
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
          Your cart stays unchanged until you confirm.
        </div>
      )}

      {/* new scoped category lines — the buyer adds the pick they want, at the qty the turn asked for
          ("5 headsets" adds 5 of the chosen model, not 1 — the old hardcoded qty ignored the request). */}
      {newLines.map((l, i) => {
        const addQty = Math.max(1, Number(l.requested_qty) || 1);
        return (
        <div key={`${l.category}-${i}`} data-testid={`multi-intent-line-${i}`} style={{ marginTop: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', textTransform: 'capitalize' }}>
            {l.category}
            {l.budget_max ? <span style={{ fontWeight: 400, color: '#6b7280' }}> · up to ${Number(l.budget_max).toLocaleString()}</span> : null}
          </div>
          {(l.results?.length ?? 0) === 0 ? (
            <div style={{ fontSize: 13, color: '#9ca3af', padding: '2px 0' }}>No in-budget options found — try widening the budget.</div>
          ) : (
            (l.results || []).slice(0, 3).map((r) => (
              <div key={r.sku || r.name}
                   style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '3px 0', fontSize: 13 }}>
                <span>{r.name}{priceText(r) ? ` — ${priceText(r)}` : ''}</span>
                <button disabled={!r.sku} onClick={() => r.sku && onAddItem(r.sku, addQty)}
                        style={{ background: r.sku ? '#fff' : '#f3f4f6', color: '#4f46e5', border: '1px solid #c7d2fe', borderRadius: 6, padding: '3px 10px', cursor: r.sku ? 'pointer' : 'default', fontWeight: 600 }}>
                  {addQty > 1 ? `Add ${addQty}` : 'Add'}
                </button>
              </div>
            ))
          )}
        </div>
        );
      })}

      <div style={{ marginTop: 10, display: 'flex', justifyContent: 'flex-end', gap: 10, alignItems: 'center' }}>
        {actionable > 1 && (
          <button data-testid="multi-intent-apply-all" onClick={applyAll}
                  style={{ background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 6, padding: '4px 12px', cursor: 'pointer', fontWeight: 700 }}>
            Apply all {actionable} changes
          </button>
        )}
        <button onClick={onDismiss}
                style={{ background: 'transparent', color: '#6b7280', border: 'none', cursor: 'pointer', fontSize: 13 }}>
          Dismiss
        </button>
      </div>
    </section>
  );
}
