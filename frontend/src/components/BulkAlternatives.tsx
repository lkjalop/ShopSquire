// Buyer-facing bulk-order alternatives (Phase 2c). Renders payload.fulfillment_options — the ordered
// choices for an unmet bulk request (partial now / transfer from the network / substitute / source the
// shortfall / reduce) BEFORE any supplier is contacted. Agnostic: option types + strings come from the
// backend (works for laptops, chairs, or shirts). Display-only; selecting is wired in a later phase.
import React from 'react';

export interface BulkAlternativeOption {
  option_id: string;
  type: string;
  title: string;
  detail: string;
  available_now?: number;
  covers_full_order?: boolean;
  transfer_plan?: { from_location: string; qty: number }[];
  sku?: string;
  price_cents?: number;
  spec_match?: number;
  spec_total?: number;
  shortfall?: number;
}

const TYPE_LABEL: Record<string, string> = {
  in_stock_now: 'In stock',
  transfer_from_network: 'Transfer',
  substitute: 'Substitute',
  source_shortfall: 'Source',
  reduce_to_available: 'Reduce',
};
const TYPE_COLOR: Record<string, string> = {
  in_stock_now: '#dcfce7',
  transfer_from_network: '#dbeafe',
  substitute: '#fef9c3',
  source_shortfall: '#ffedd5',
  reduce_to_available: '#f3f4f6',
};

export default function BulkAlternatives({ options }: { options: BulkAlternativeOption[] }) {
  if (!options || options.length === 0) return null;
  return (
    <div data-testid="bulk-alternatives"
         style={{ margin: '8px 0', padding: 10, border: '1px solid #e5e7eb', borderRadius: 10, background: '#fafafa' }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>Fulfilment options for your bulk order</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {options.map((o) => (
          <div key={o.option_id}
               style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 8px',
                        borderRadius: 8, background: '#fff', border: '1px solid #eee' }}>
            <span style={{ flex: '0 0 auto', padding: '1px 7px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                           background: TYPE_COLOR[o.type] || '#eee', color: '#374151' }}>
              {TYPE_LABEL[o.type] || o.type}
            </span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{o.title}</div>
              <div style={{ fontSize: 12, color: '#6b7280' }}>{o.detail}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 6 }}>
        Choosing an option doesn’t place an order — sourcing drafts an RFQ for human review.
      </div>
    </div>
  );
}
