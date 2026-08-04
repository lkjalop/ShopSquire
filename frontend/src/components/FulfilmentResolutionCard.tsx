import React from 'react';
import type { FulfilmentResolution, FulfilmentOption } from '../lib/fulfilmentResolution';

type Props = {
  resolution: FulfilmentResolution;
  onChoose: (choice: FulfilmentOption) => void;
};

const OPTION_LABEL: Record<FulfilmentOption, string> = {
  source_shortfall: 'Source the shortfall',
  mixed_alternative: 'Fill remainder with an alternative',
  change_requirement: 'Change the requirement',
};

export default function FulfilmentResolutionCard({ resolution, onChoose }: Props) {
  const options = new Set(resolution.options || []);
  const transfers = resolution.transfer_plan || [];
  return (
    <section aria-label="Resolve fulfilment" style={{
      marginTop: 8,
      border: '1px solid #b8c5d6',
      borderRadius: 6,
      padding: 10,
      background: '#f7f9fc',
      color: '#172033',
    }}>
      <div style={{ fontWeight: 700 }}>
        Can’t fulfil {resolution.requested} × {resolution.product_name} as-is
      </div>
      <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18, fontSize: 14, lineHeight: 1.5 }}>
        {resolution.local_now > 0 && <li>{resolution.local_now} in stock now</li>}
        {resolution.network_transfer > 0 && (
          <li>
            {resolution.network_transfer} transferred from{' '}
            {transfers.map((t) => t.from_location).filter(Boolean).join(', ') || 'other locations'}
          </li>
        )}
        {resolution.supplier_rfq_qty > 0 && (
          <li>
            {resolution.supplier_rfq_qty} sourced via supplier RFQ{' '}
            <em>(requested, not confirmed — draft only)</em>
          </li>
        )}
      </ul>
      <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {(['source_shortfall', 'mixed_alternative', 'change_requirement'] as FulfilmentOption[])
          .filter((opt) => options.has(opt))
          .map((opt) => (
            <button key={opt} type="button" onClick={() => onChoose(opt)}>
              {OPTION_LABEL[opt]}
            </button>
          ))}
      </div>
      <div style={{ marginTop: 6, fontSize: 12, color: '#5a6b85' }}>
        Nothing is ordered or sent to a supplier until you approve.
      </div>
    </section>
  );
}
