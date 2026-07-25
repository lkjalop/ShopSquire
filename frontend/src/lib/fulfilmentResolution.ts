/**
 * Fulfilment resolution — buyer-facing, governed options when local + network stock
 * cannot meet a requested quantity. Pure data-shaping over the backend
 * `combined_availability` result (multi_location_availability.combined_availability):
 * it NEVER claims a supplier has live stock — the shortfall is an RFQ request only.
 */

export type CombinedAvailability = {
  sku: string;
  requested: number;
  local_now: number;
  network_transfer: number;
  transfer_plan: Array<{ from_location: string; qty: number }>;
  supplier_rfq_qty: number;
  fillable_from_network: boolean;
  /** Always 'unconfirmed_rfq' — a request quantity, not a live-ATP claim. */
  supplier_availability: string;
};

export type FulfilmentAlternative = { sku: string; name: string; price_cents?: number };

export type FulfilmentOption = 'source_shortfall' | 'mixed_alternative' | 'change_requirement';

export type FulfilmentResolution = {
  kind: 'combined_availability';
  sku: string;
  product_name: string;
  currency?: string;
  requested: number;
  local_now: number;
  network_transfer: number;
  transfer_plan: Array<{ from_location: string; qty: number }>;
  supplier_rfq_qty: number;
  supplier_confirmed: false;
  options: FulfilmentOption[];
  alternatives: FulfilmentAlternative[];
  requires_confirmation: true;
};

/**
 * Build the governed resolution, or null when the network fully covers demand
 * (no decision to surface). Options offered:
 *   • source_shortfall   — ship local now + transfer + RFQ the balance (always, when short)
 *   • mixed_alternative  — fill the remainder from in-catalog alternatives (only if any exist)
 *   • change_requirement — reduce quantity / increase budget / relax a constraint (always)
 */
export function buildFulfilmentResolution(
  combined: CombinedAvailability,
  opts: { productName: string; currency?: string; alternatives?: FulfilmentAlternative[] },
): FulfilmentResolution | null {
  const requested = Math.max(0, Number(combined?.requested) || 0);
  const rfq = Math.max(0, Number(combined?.supplier_rfq_qty) || 0);
  const transfer = Math.max(0, Number(combined?.network_transfer) || 0);
  // Nothing to resolve when the network already covers the order (no shortfall AND
  // no cross-location transfer the buyer must approve).
  if (rfq === 0 && transfer === 0) return null;

  const alternatives = (opts.alternatives || []).filter((a) => a && a.sku);
  const options: FulfilmentOption[] = ['source_shortfall'];
  if (rfq > 0 && alternatives.length > 0) options.push('mixed_alternative');
  options.push('change_requirement');

  return {
    kind: 'combined_availability',
    sku: String(combined.sku || ''),
    product_name: opts.productName,
    currency: opts.currency,
    requested,
    local_now: Math.max(0, Number(combined.local_now) || 0),
    network_transfer: transfer,
    transfer_plan: (combined.transfer_plan || []).filter((t) => t && Number(t.qty) > 0),
    supplier_rfq_qty: rfq,
    supplier_confirmed: false,
    options,
    alternatives,
    requires_confirmation: true,
  };
}
