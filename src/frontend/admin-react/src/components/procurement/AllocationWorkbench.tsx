import React, { useEffect, useState } from 'react';

import { fetchAllocationWorkbench, type AllocationWorkbenchView } from '../../api';

const age = (seconds: number) => {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
};

const money = (cents: number, currency: string) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(cents / 100);

export function AllocationWorkbench() {
  const [view, setView] = useState<AllocationWorkbenchView | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const selectedSku = new URLSearchParams(window.location.search).get('allocation_sku') || undefined;
  const load = () => {
    setState('loading');
    fetchAllocationWorkbench(selectedSku)
      .then((result) => { setView(result); setState('ready'); })
      .catch(() => { setView(null); setState('unavailable'); });
  };
  useEffect(load, []);

  if (state === 'loading') return <div data-testid="allocation-workbench-loading">Loading allocation ledger...</div>;
  if (!view) {
    return (
      <div role="status" data-testid="allocation-workbench-unavailable"
           style={{ border: '1px solid #f59e0b', background: '#fffbeb', padding: 10, borderRadius: 8 }}>
        Allocation ledger unavailable. Existing procurement execution is unchanged.
        <button style={{ marginLeft: 8 }} onClick={load}>Retry</button>
      </div>
    );
  }
  const summary = view.summary;
  const recoveryOptions = view.recovery_options || [];
  return (
    <section data-testid="allocation-workbench"
             style={{ border: '1px solid #bfdbfe', background: '#eff6ff', borderRadius: 10, padding: 12, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <h3 style={{ margin: 0 }}>Supply Allocation Workbench{selectedSku ? ` · ${selectedSku}` : ''}</h3>
        <button onClick={load}>Refresh ledger</button>
      </div>
      <div style={{ color: '#475569', fontSize: 12, marginTop: 3 }}>
        Shadow allocation · legacy reservations still execute · buyers anonymized
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(135px,1fr))', gap: 8, marginTop: 10 }}>
        <Metric label="Committed" value={summary.committed_quantity} />
        <Metric label="Allocated" value={summary.allocated_quantity} />
        <Metric label="Shortfall" value={summary.shortfall_quantity} concern={summary.shortfall_quantity > 0} />
        <Metric label="Supplier confirmed" value={summary.supplier_confirmed_quantity} />
        <Metric label="Supplier unresolved" value={summary.supplier_unresolved_quantity}
                concern={summary.supplier_unresolved_quantity > 0} />
        <Metric label="Allocation pressure" value={`${Math.round(summary.allocation_pressure * 100)}%`} concern={summary.allocation_pressure > 0} />
        <Metric label="Oldest queue" value={age(summary.oldest_queue_age_seconds)} concern={summary.oldest_queue_age_seconds > 3600} />
      </div>
      {view.demands.length > 0 && (
        <div style={{ overflowX: 'auto', marginTop: 10 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr><th>Demand</th><th>SKU</th><th>Stage</th><th>Requested</th><th>Allocated</th><th>Shortfall</th><th>Queue</th><th>Promise</th></tr></thead>
            <tbody>{view.demands.map((demand) => (
              <tr key={demand.demand_ref} data-testid="allocation-demand-row">
                <td>{demand.demand_ref}</td><td>{demand.sku}</td><td>{demand.stage}</td>
                <td>{demand.requested_quantity}</td><td>{demand.allocated_quantity}</td>
                <td>{demand.shortfall_quantity}</td><td>{age(demand.queue_age_seconds)}</td>
                <td>{demand.promise_state || 'not assessed'}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {view.sourcing_batches.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary>SKU sourcing batches · {view.sourcing_batches.length}</summary>
          {view.sourcing_batches.map((batch) => (
            <div key={batch.batch_ref} data-testid="allocation-sourcing-batch" style={{ marginTop: 6 }}>
              <strong>{batch.batch_ref}</strong> · {batch.quantity} × {batch.sku} · {batch.child_demand_count} anonymized child demand(s) · {batch.status}
            </div>
          ))}
        </details>
      )}
      {(view.sourcing_waves || []).length > 0 && (
        <div style={{ marginTop: 10 }} data-testid="allocation-sourcing-waves">
          <strong>Supplier shipment waves</strong>
          {view.sourcing_waves.map((wave) => (
            <div key={wave.wave_ref} data-testid="allocation-sourcing-wave"
                 style={{ background: '#fff', border: '1px solid #bfdbfe', borderRadius: 8, padding: 8, marginTop: 6 }}>
              <div><strong>{wave.wave_ref}</strong> · {wave.supplier_id} / {wave.supplier_facility_id}</div>
              <div>{wave.batch_count} SKU batch(es) · {wave.total_quantity} units · {wave.incoterm} · {wave.currency}</div>
              <div>Freight {money(wave.consolidated_freight_cents, wave.currency)} + handling {money(wave.handling_cents, wave.currency)}</div>
              <div style={{ color: wave.estimated_savings_cents >= 0 ? '#166534' : '#b91c1c' }}>
                Estimated consolidation {wave.estimated_savings_cents >= 0 ? 'saving' : 'cost'}: {money(Math.abs(wave.estimated_savings_cents), wave.currency)}
              </div>
              <small>Estimate only · no RFQ, PO, shipment or payment executed</small>
            </div>
          ))}
        </div>
      )}
      {(view.route_proposals || []).length > 0 && (
        <div style={{ marginTop: 10 }} data-testid="allocation-route-proposals">
          <strong>Fulfillment route proposals</strong>
          {view.route_proposals.map((route) => (
            <div key={route.proposal_ref} data-testid="allocation-route-proposal"
                 style={{ background: '#fff', border: '1px solid #cbd5e1', borderRadius: 8, padding: 8, marginTop: 6 }}>
              <div><strong>{route.mode.replace(/_/g, ' ')}</strong> · {route.status}</div>
              <div>ETA {route.eta_days.min ?? '?'}–{route.eta_days.max ?? '?'} days · calculated range, not a promise</div>
              <div>Destination shared as token: {route.destination_token}</div>
              <div>Privacy authority: {route.privacy.status}{route.privacy.jurisdiction ? ` · ${route.privacy.jurisdiction}` : ''}</div>
              {route.state_prevented && <div style={{ color: '#b45309' }}>Prevented: {route.state_prevented}</div>}
            </div>
          ))}
        </div>
      )}
      {recoveryOptions.length > 0 && (
        <div style={{ marginTop: 10 }} data-testid="allocation-recovery-options">
          <strong>Grounded recovery options</strong>
          {recoveryOptions.map((recovery) => (
            <div key={recovery.batch_ref}
                 style={{ background: '#fff', border: '1px solid #fdba74', borderRadius: 8, padding: 8, marginTop: 6 }}>
              <div><strong>{recovery.batch_ref}</strong> · {recovery.unresolved_child_count} affected anonymized demand(s)</div>
              {recovery.alternative_suppliers.map((supplier) => (
                <div key={supplier.supplier_id} data-testid="allocation-alternative-supplier" style={{ marginTop: 5 }}>
                  Alternative supplier: <strong>{supplier.supplier_name}</strong> · availability <strong>unknown</strong> · confirmation required
                  <small style={{ display: 'block', color: '#64748b' }}>
                    Tenant-approved mapping · {supplier.authority.freshness} · {supplier.authority.source} {supplier.authority.source_version}
                  </small>
                </div>
              ))}
              {recovery.qualified_substitutes.map((substitute) => (
                <div key={substitute.sku} data-testid="allocation-qualified-substitute" style={{ marginTop: 5 }}>
                  Qualified substitute: <strong>{substitute.sku}</strong> · availability <strong>unknown</strong> · confirmation required
                </div>
              ))}
              {recovery.status === 'insufficient_evidence' && (
                <div style={{ color: '#b45309', marginTop: 5 }}>
                  No fresh tenant-approved recovery mapping. Operator review required.
                </div>
              )}
              <small style={{ display: 'block', marginTop: 5 }}>
                Prevented: unconfirmed supply presented as available · no supplier contact or order executed
              </small>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, concern = false }: { label: string; value: React.ReactNode; concern?: boolean }) {
  return (
    <div style={{ background: concern ? '#fff7ed' : '#fff', border: `1px solid ${concern ? '#fdba74' : '#dbeafe'}`, borderRadius: 8, padding: 8 }}>
      <div style={{ color: '#64748b', fontSize: 11 }}>{label}</div><strong>{value}</strong>
    </div>
  );
}

export default AllocationWorkbench;
