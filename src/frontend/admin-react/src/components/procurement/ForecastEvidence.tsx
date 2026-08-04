import React, { useEffect, useState } from 'react';
import {
  fetchInventoryForecast,
  materializeInventoryForecast,
  type InventoryForecastIntelligence,
} from '../../api/fulfillment';


const metric = (value?: number | null, status?: string) => {
  if (value == null) return status?.replace(/_/g, ' ') || 'undefined';
  return value.toFixed(3);
};

const modelLabel: Record<string, string> = {
  seasonal_naive: 'Seasonal naïve',
  ewma: 'EWMA',
  croston_sba: 'Croston/SBA',
  tsb: 'TSB',
};

export default function ForecastEvidence({
  sku,
  leadTimeDays = 14,
}: {
  sku: string;
  leadTimeDays?: number;
}) {
  const [data, setData] = useState<InventoryForecastIntelligence | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async (seal = false) => {
    if (!sku) return;
    setBusy(true);
    setError('');
    try {
      setData(seal
        ? await materializeInventoryForecast(sku, leadTimeDays)
        : await fetchInventoryForecast(sku, leadTimeDays));
    } catch (err: any) {
      setError(err?.message || 'Forecast evidence is unavailable.');
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { void load(false); }, [sku, leadTimeDays]);
  if (!sku) return null;

  return (
    <details open data-testid="forecast-evidence"
      style={{ margin: '8px 0', padding: 10, border: '1px solid #cbd5e1', borderRadius: 8 }}>
      <summary><strong>Forecast evidence · {sku}</strong></summary>
      {busy && !data && <div>Loading reconciled history…</div>}
      {error && <div role="alert" style={{ color: '#991b1b' }}>{error}</div>}
      {data && (
        <>
          <div style={{ margin: '6px 0', fontSize: 13 }}>
            <strong>{data.status.replace(/_/g, ' ')}</strong>
            {' · '}ABC {data.segmentation.abc_class || 'undefined'}
            {' · '}XYZ {data.segmentation.xyz_class || 'undefined'}
            {' · '}{data.history_points} daily points
            {' · '}{data.horizon.days}-day supplier lead-time horizon
          </div>
          <div data-testid="forecast-trust-labels"
               style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 12, color: '#475569', marginBottom: 6 }}>
            <span className="badge">Authority: {data.authority.replace(/_/g, ' ').toUpperCase()}</span>
            <span className="badge">Autonomy: {data.can_increase_autonomy ? 'eligible' : 'cannot increase autonomy'}</span>
            <span className="badge">Source: {data.source.status.replace(/_/g, ' ').toUpperCase()}</span>
            <span className="badge">Freshness: {data.source.watermark ? `THROUGH ${data.source.watermark}` : 'NOT REPORTED'}</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th align="left">Model</th>
                  <th align="right">Lead-time units</th>
                  <th align="right">WAPE</th>
                  <th align="right">MASE</th>
                  <th align="right">Bias</th>
                  <th align="left">Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.models).map(([name, row]) => (
                  <tr key={name} data-testid={`forecast-model-${name}`}
                    style={{ background: data.selected_model === name ? '#ecfdf5' : undefined }}>
                    <td>{modelLabel[name] || name}{data.selected_model === name ? ' · selected' : ''}</td>
                    <td align="right">{row.horizon_units ?? 'undefined'}</td>
                    <td align="right">{metric(row.wape, row.wape_status)}</td>
                    <td align="right">{metric(row.mase, row.mase_status)}</td>
                    <td align="right">{metric(row.bias)}</td>
                    <td>{row.status.replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button disabled={busy || data.materialized} onClick={() => void load(true)}
            style={{ marginTop: 8 }}>
            {data.materialized ? 'Evaluation sealed' : 'Seal shadow evaluation'}
          </button>
          {data.evaluation_id && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
              Evidence {data.evaluation_id.slice(0, 12)} · {data.computation_version}
            </div>
          )}
        </>
      )}
    </details>
  );
}
