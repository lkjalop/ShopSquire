/**
 * Human-readable explanation for a procurement agent step — "What happened / Why" above the raw JSON
 * in the Decision Trace drill-down (reviewer: "raw JSON is for engineers; a demo needs the sentence").
 * Deterministic template over the recorded payload — derives ONLY from recorded fields, never invents.
 * Unknown event types return null and the drill-down shows JSON alone. Pure → unit-testable.
 */
export interface ProcExplanation {
  what: string;
  why?: string;
}

export function explainProcEvent(eventType: string, p: Record<string, any>): ProcExplanation | null {
  const t = String(eventType || '');
  switch (t) {
    case 'bulk_availability_assessed': {
      const req = p.order_qty ?? '?';
      const stock = p.in_stock ?? '?';
      const short = Number(p.shortfall ?? 0);
      return {
        what: `Checked stock for ${p.sku || 'the requested line'}: ${stock} in stock against ${req} requested.`,
        why: short > 0
          ? `${short} unit(s) short — the shortfall routes to supplier sourcing instead of over-promising stock.`
          : 'Fully coverable from stock — no supplier sourcing needed for this line.',
      };
    }
    case 'market_intelligence_assessed': {
      const n = p.signal_count ?? 0;
      return {
        what: n > 0
          ? `Read ${n} active market signal(s) scoped to this line and recommended: ${p.recommendation || '—'}.`
          : 'No active market signals for this line (internal-only mode).',
        why: p.rationale || undefined,
      };
    }
    case 'alternatives_generated': {
      const kinds = Array.isArray(p.types) ? p.types.join(', ') : '';
      return {
        what: `Built ${p.count ?? 0} fulfilment alternative(s)${kinds ? ` (${kinds})` : ''} for ${p.sku || 'the line'}.`,
        why: 'The buyer gets a workable next step (partial ship / network transfer / substitute) instead of a dead end.',
      };
    }
    case 'sourcing_previewed':
      return {
        what: 'Previewed the sourcing split — which units ship from stock and which need a supplier.',
        why: 'Nothing is committed at preview; the buyer confirms the plan before any case is opened.',
      };
    case 'procurement_case_opened':
      return {
        what: `Opened a durable procurement case${p.case_id ? ` (${String(p.case_id).slice(0, 8)})` : ''} for the confirmed shortfall.`,
        why: 'GATE 1 passed — buyer commitment recorded; no supplier is contacted until a human approves the send (GATE 2).',
      };
    case 'supplier_selected':
      return {
        what: `Selected supplier ${p.supplier_ref || '—'} for ${p.item_ref || 'the line'} (qty ${p.quantity ?? '—'}).`,
        why: 'Ranked from the approved allowlist on reliability, terms and history — never from buyer text.',
      };
    case 'supplier_channel_resolved':
      return {
        what: `Resolved the supplier's preferred channel: ${String(p.channel || 'email').toUpperCase()}.`,
        why: p.rationale || undefined,
      };
    default:
      return null;
  }
}
