import React from 'react';

export type AffordabilityResolution = {
  kind: 'total_budget_exceeded';
  sku: string;
  product_name: string;
  currency?: string;
  requested_quantity: number;
  max_affordable_quantity: number;
  current_unit_price_cents: number;
  cheaper_unit_price_max_cents: number;
  budget_max_cents: number;
  proposed_total_cents: number;
  other_lines_total_cents?: number;
  choices: Array<'reduce_quantity' | 'increase_budget' | 'choose_cheaper_product'>;
  requires_confirmation: boolean;
};

type Props = {
  resolution: AffordabilityResolution;
  onChoose: (choice: AffordabilityResolution['choices'][number]) => void;
};

function money(cents: number, currency?: string): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency || 'AUD',
    maximumFractionDigits: 0,
  }).format(Math.max(0, Number(cents) || 0) / 100);
}

export default function AffordabilityResolutionCard({ resolution, onChoose }: Props) {
  const available = new Set(resolution.choices || []);
  return (
    <section aria-label="Resolve total budget" style={{
      marginTop: 8,
      border: '1px solid #b8c5d6',
      borderRadius: 6,
      padding: 10,
      background: '#f7f9fc',
      color: '#172033',
    }}>
      <div style={{ fontWeight: 700 }}>Order total needs a decision</div>
      <div style={{ marginTop: 4, fontSize: 14, lineHeight: 1.4 }}>
        {resolution.requested_quantity} × {resolution.product_name} would make the cart{' '}
        {money(resolution.proposed_total_cents, resolution.currency)}, above the preserved{' '}
        {money(resolution.budget_max_cents, resolution.currency)} total budget. Nothing changed.
      </div>
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {available.has('reduce_quantity') && resolution.max_affordable_quantity > 0 && (
          <button type="button" onClick={() => onChoose('reduce_quantity')}>
            Reduce to {resolution.max_affordable_quantity}
          </button>
        )}
        {available.has('increase_budget') && (
          <button type="button" onClick={() => onChoose('increase_budget')}>
            Increase budget to {money(resolution.proposed_total_cents, resolution.currency)}
          </button>
        )}
        {available.has('choose_cheaper_product') && (
          <button type="button" onClick={() => onChoose('choose_cheaper_product')}>
            Choose a cheaper product
          </button>
        )}
      </div>
    </section>
  );
}
