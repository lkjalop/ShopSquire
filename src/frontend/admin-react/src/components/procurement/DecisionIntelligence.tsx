import React, { useEffect, useState } from 'react';
import {
  fcDecisionIntelligence,
  type ProcurementDecisionIntelligence,
} from '../../api/fulfillment';

const units = (value: unknown) => (
  typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : 'undefined'
);

export default function DecisionIntelligence({ caseId }: { caseId: string }) {
  const [data, setData] = useState<ProcurementDecisionIntelligence | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setData(null);
    setError('');
    if (!caseId) return;
    fcDecisionIntelligence(caseId)
      .then(setData)
      .catch((err: any) => setError(err?.message || 'Decision evidence is unavailable.'));
  }, [caseId]);

  if (!caseId) return null;
  return (
    <details open data-testid="decision-intelligence"
      style={{ margin: '8px 0', padding: 10, border: '1px solid #94a3b8', borderRadius: 8 }}>
      <summary><strong>Immutable decision context</strong></summary>
      {error && <div role="alert" style={{ color: '#991b1b' }}>{error}</div>}
      {!error && !data && <div>Loading decision evidence…</div>}
      {data?.status === 'not_materialized' && (
        <div data-testid="decision-not-materialized" style={{ marginTop: 6, color: '#92400e' }}>
          No immutable decision context has been sealed for this case. Replenishment and landed-cost
          values are undefined—not zero.
        </div>
      )}
      {data?.context && (
        <>
          <div style={{ marginTop: 6, fontSize: 13 }}>
            <strong>{data.context.source_authority}</strong>
            {' · '}immutable case version {data.context.case_version_id.slice(0, 12)}
            {' · '}facts {data.context.facts_hash.slice(0, 12)}
          </div>
          <div style={{ fontSize: 12, color: '#475569' }}>
            Captured {data.context.created_at} by {data.context.created_by}. Provenance is retained;
            extracted conversation observations cannot overwrite authoritative facts.
          </div>
          <div data-testid="decision-exact-inputs" style={{ marginTop: 6, fontSize: 12 }}>
            Demand {units(data.context.facts?.demand?.mean_daily)}/day
            {' · '}variance {units(data.context.facts?.demand?.variance_daily)}
            {' · '}lead time {units(data.context.facts?.supplier_lead_time?.mean_days)} days
            {' · '}ATP {units(data.context.facts?.inventory?.current_atp)}
            {' · '}incoming {units(data.context.facts?.inventory?.incoming_supply)}
            {' · '}service level {typeof data.context.facts?.service_level === 'number'
              ? `${(data.context.facts.service_level * 100).toFixed(1)}%` : 'undefined'}
          </div>
          {data.proposal ? (
            <div data-testid="replenishment-proposal"
              style={{ marginTop: 8, padding: 8, background: '#fffbeb', borderRadius: 6 }}>
              <strong>Replenishment proposal only</strong>
              {' · '}{data.proposal.status.replace(/_/g, ' ')}
              <div>
                Safety stock {units(data.proposal.result.safety_stock_units)}
                {' · '}reorder point {units(data.proposal.result.reorder_point_units)}
                {' · '}suggested order {units(data.proposal.result.suggested_order_units)}
                {' · '}MOQ {units(data.proposal.result.moq_units)}
                {' · '}pack {units(data.proposal.result.pack_size_units)}
              </div>
              <div>Blocked: {data.proposal.blocked_reasons.map((reason) => reason.replace(/_/g, ' ')).join(', ')}</div>
            </div>
          ) : (
            <div style={{ marginTop: 6 }}>No replenishment proposal has been computed from this snapshot.</div>
          )}
          {data.comparison ? (
            <div data-testid="landed-cost-comparison"
              style={{ marginTop: 8, padding: 8, background: '#eff6ff', borderRadius: 6 }}>
              <strong>Landed-cost comparison only · cannot authorize purchase</strong>
              <div>
                Recommended {data.comparison.recommended?.quote_id || 'undefined'}
                {' · '}comparable unit cost {
                  data.comparison.recommended?.comparable_landed_unit_minor ?? 'undefined'
                } {data.comparison.recommended?.currency || ''}
                {' · '}{data.comparison.recommended?.uom || ''}
              </div>
              <div>{data.comparison.ranked.length} comparable · {data.comparison.excluded.length} excluded</div>
            </div>
          ) : (
            <div style={{ marginTop: 6 }}>No approved-FX, comparable-UoM quote comparison is available.</div>
          )}
        </>
      )}
    </details>
  );
}
