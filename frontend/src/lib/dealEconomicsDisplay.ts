export type DealProjection = {
  verdict?: string;
  currency?: string;
  quantity?: number;
  list_unit_cents?: number;
  wholesale_unit_cents?: number;
  gross_per_unit_cents?: number;
  margin_pct?: number;
  projected_profit_cents?: number;
  max_discount_cents?: number;
  discount_authorized?: boolean;
  cost_is_estimated?: boolean;
  landed_cost_complete?: boolean;
  simulation_only?: boolean;
  bulk_breaks?: Array<{
    min_qty?: number;
    discount_pct?: number;
    estimated_supplier_unit_cents?: number;
    margin_pct?: number;
    projected_profit_cents_at_min_qty?: number;
    pricing_authorized?: boolean;
  }>;
};

export function formatDealMoney(cents: unknown, currency = 'AUD'): string {
  const value = Number(cents);
  if (!Number.isFinite(value)) return '--';
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: String(currency || 'AUD').toUpperCase(),
    maximumFractionDigits: 0,
  }).format(value / 100);
}

export function dealEconomicsStatus(projection: DealProjection) {
  const verdict = String(projection.verdict || 'unknown').replace(/_/g, ' ').toUpperCase();
  const estimated = Boolean(
    projection.cost_is_estimated || projection.simulation_only || !projection.landed_cost_complete,
  );
  return {
    verdict,
    estimated,
    costLabel: estimated ? 'Estimated supplier cost' : 'Validated landed cost',
    discountLabel: projection.discount_authorized
      ? `Authorized headroom ${formatDealMoney(projection.max_discount_cents, projection.currency)}`
      : 'Buyer discount locked until landed cost is validated',
  };
}
