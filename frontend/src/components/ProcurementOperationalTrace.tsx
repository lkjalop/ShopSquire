import React from 'react';


type ProcurementOperationalTraceProps = {
  allocationView: any;
};


const rowStyle: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', gap: 12, padding: '4px 0',
};

const nestedStyle: React.CSSProperties = {
  borderTop: '1px solid #bfdbfe', marginTop: 8, paddingTop: 8,
};

function humanize(value: unknown): string {
  return String(value || 'unknown').replace(/_/g, ' ');
}

function percent(value: unknown): number {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? Math.round(numeric * 100) : 0;
}

function duration(seconds: unknown): string {
  const numeric = Number(seconds);
  if (!Number.isFinite(numeric)) return 'not observed';
  if (numeric < 60) return `${Math.max(0, Math.round(numeric))} sec`;
  return `${Math.max(0, Math.round(numeric / 60))} min`;
}

function slaStatus(value: unknown): string {
  const normalized = String(value || 'unknown').toLowerCase();
  if (normalized === 'within_sla') return 'within SLA';
  if (normalized === 'breached') return 'breached';
  return humanize(normalized);
}

function money(cents: unknown, currency: unknown): string {
  const numeric = Number(cents);
  if (!Number.isFinite(numeric)) return 'unavailable';
  return `${String(currency || 'AUD')} ${(numeric / 100).toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}`;
}

function rangeLabel(value: unknown, label: string): string | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  return `${label} ${value[0]}–${value[1]}d`;
}


export default function ProcurementOperationalTrace({
  allocationView,
}: ProcurementOperationalTraceProps) {
  const summary = allocationView?.summary;
  if (!summary) return null;

  return (
    <section
      aria-label="Allocation and supplier operations"
      data-testid="proc-allocation-trace"
      style={{
        border: '1px solid #bfdbfe', background: '#eff6ff', borderRadius: 8,
        padding: '10px 12px', marginBottom: 12, fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <strong>Allocation and sourcing state</strong>
        <span>Shadow allocation · legacy reservations execute</span>
      </div>
      <div style={rowStyle}>
        <span>Authority</span><span>Shadow allocation</span>
      </div>
      <div style={rowStyle}>
        <span>Committed / allocated</span>
        <span>{summary.committed_quantity} / {summary.allocated_quantity}</span>
      </div>
      <div style={rowStyle}>
        <span>Allocation pressure</span><span>{percent(summary.allocation_pressure)}%</span>
      </div>
      <div style={rowStyle}>
        <span>Oldest demand queue age</span><span>{duration(summary.oldest_queue_age_seconds)}</span>
      </div>
      <div style={rowStyle}>
        <span>State changed</span>
        <span>{summary.allocated_quantity} unit(s) backed by current allocation evidence</span>
      </div>
      <div style={rowStyle}>
        <span>State prevented</span>
        <span>{summary.shortfall_quantity > 0
          ? `${summary.shortfall_quantity} unconfirmed unit(s) cannot become a delivery promise`
          : 'No unresolved allocation block'}</span>
      </div>

      {(allocationView.sourcing_batches || []).map((batch: any) => (
        <div key={batch.batch_ref} data-testid="proc-consolidated-demand-count" style={rowStyle}>
          <span>{batch.batch_ref}</span>
          <span>{batch.quantity} unit(s) · {batch.child_demand_count} anonymized child demand(s) · {batch.status}</span>
        </div>
      ))}

      {(allocationView.supplier_pressure || []).map((pressure: any) => (
        <div
          key={`${pressure.supplier_id}:${pressure.supplier_facility_id}`}
          data-testid="proc-supplier-pressure"
          style={nestedStyle}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <strong>{pressure.supplier_id} / {pressure.supplier_facility_id}</strong>
            <span>{humanize(pressure.status)}</span>
          </div>
          {pressure.queue && (
            <div>
              {pressure.queue.open_requests} open request(s) · {pressure.queue.open_units} open unit(s)
              {' · '}{percent(pressure.queue.open_unit_utilization)}% open-unit envelope
            </div>
          )}
          <div>
            Response SLA: {slaStatus(pressure.response_sla?.status)}
            {pressure.response_sla?.queue_age_seconds != null
              ? ` · oldest unacknowledged ${duration(pressure.response_sla.queue_age_seconds)}`
              : ''}
          </div>
          <div>
            {pressure.source_health?.source_id || 'source unavailable'} ·{' '}
            {pressure.source_health?.source_version || 'version unavailable'} ·{' '}
            {humanize(pressure.source_health?.status)}
          </div>
          <div>New supplier contact: {humanize(pressure.external_contact_authority)}</div>
          {Array.isArray(pressure.reason_codes) && pressure.reason_codes.length > 0 && (
            <div>Reason: {pressure.reason_codes.map(humanize).join(' · ')}</div>
          )}
        </div>
      ))}

      {(allocationView.sourcing_waves || []).map((wave: any) => (
        <div key={wave.wave_ref} data-testid="proc-sourcing-wave" style={nestedStyle}>
          <strong>{wave.wave_ref}</strong> · {wave.batch_count} SKU batch(es) · {wave.total_quantity} units
          <div>{wave.supplier_id} / {wave.supplier_facility_id} · {wave.incoterm} · {wave.currency}</div>
          <div>
            Estimated freight saving {money(Math.max(0, Number(wave.estimated_savings_cents || 0)), wave.currency)}
            {' · '}proposal only
          </div>
        </div>
      ))}

      {(allocationView.route_proposals || []).map((route: any) => {
        const components = [
          rangeLabel(route.components?.dispatch_days, 'dispatch'),
          rangeLabel(route.components?.transit_days, 'transit'),
          rangeLabel(route.components?.inspection_days, 'inspection'),
          rangeLabel(route.components?.cross_dock_days, 'cross-dock'),
          rangeLabel(route.components?.final_mile_days, 'final mile'),
        ].filter(Boolean);
        return (
          <div key={route.proposal_ref} data-testid="proc-route-proposal" style={nestedStyle}>
            <strong>{humanize(route.mode)}</strong> · {humanize(route.status)}
            <div>
              ETA {route?.eta_days?.min ?? '?'}–{route?.eta_days?.max ?? '?'} days
              {' · '}calculated range, not a promise
            </div>
            {components.length > 0 && <div>{components.join(' · ')}</div>}
            <div>Destination authority: token only · privacy {humanize(route?.privacy?.status || 'not required')}</div>
            {route.state_prevented && <div>State prevented: {humanize(route.state_prevented)}</div>}
          </div>
        );
      })}
    </section>
  );
}
