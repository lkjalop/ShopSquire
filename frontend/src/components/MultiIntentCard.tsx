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
  // Only show an amendment row for a line THIS turn actually changed (amended === true) and to a real
  // positive qty — never for a carried-forward/unchanged prior line (that would be a spurious confirm that
  // adds/changes an item the buyer didn't ask about) nor for qty<=0 (which would silently remove the line).
  const amendments = lines.filter(
    (l) => l.scope === 'prior' && l.ref && l.amended === true && typeof l.requested_qty === 'number' && (l.requested_qty as number) >= 1,
  );
  const newLines = lines.filter((l) => l.scope === 'new');
  const hasNewPicks = newLines.some((l) => (l.results?.length ?? 0) > 0);
  // Nothing to confirm → render nothing (a plain single-intent turn never reaches here anyway).
  if (!amendments.length && !hasNewPicks) return null;

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

      {/* qty amendment on the already-chosen item — confirm, never auto-apply */}
      {amendments.map((l) => (
        <div key={l.ref} data-testid={`multi-intent-amend-${l.ref}`}
             style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '4px 0' }}>
          <span style={{ fontSize: 14 }}>
            Change <strong>{l.name || l.ref}</strong> quantity to <strong>{l.requested_qty}</strong>
          </span>
          <button onClick={() => onAmendQty(l.ref as string, l.requested_qty as number)}
                  style={{ background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontWeight: 600 }}>
            Confirm qty
          </button>
        </div>
      ))}

      {/* new scoped category lines — the buyer adds the pick they want */}
      {newLines.map((l, i) => (
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
                <button disabled={!r.sku} onClick={() => r.sku && onAddItem(r.sku, 1)}
                        style={{ background: r.sku ? '#fff' : '#f3f4f6', color: '#4f46e5', border: '1px solid #c7d2fe', borderRadius: 6, padding: '3px 10px', cursor: r.sku ? 'pointer' : 'default', fontWeight: 600 }}>
                  Add
                </button>
              </div>
            ))
          )}
        </div>
      ))}

      <div style={{ marginTop: 10, textAlign: 'right' }}>
        <button onClick={onDismiss}
                style={{ background: 'transparent', color: '#6b7280', border: 'none', cursor: 'pointer', fontSize: 13 }}>
          Dismiss
        </button>
      </div>
    </section>
  );
}
