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

function safeText(value: unknown, fallback = 'not recorded'): string {
  const rendered = String(value ?? '').trim();
  return rendered || fallback;
}

function asArray(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
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

function transmissionStatus(value: unknown): string {
  const normalized = String(value || 'blocked_unknown').toLowerCase();
  if (normalized === 'transmit_now') return 'transmit now';
  if (normalized === 'queue_until_open') return 'contact queued until verified opening';
  return 'blocked — timing authority unknown';
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

function impactRange(value: any, suffix = ''): string {
  if (Array.isArray(value) && value.length >= 2) return `${value[0]}–${value[1]}${suffix}`;
  if (value && typeof value === 'object' && value.min != null && value.max != null) {
    return `${value.min}–${value.max}${suffix}`;
  }
  return value == null ? 'not calculated' : `${value}${suffix}`;
}

function boundedRange(value: any): any {
  if (value && typeof value === 'object' && value.low != null && value.high != null) {
    return [value.low, value.high];
  }
  return value;
}

function marginRange(value: any): any {
  const normalized = boundedRange(value);
  if (Array.isArray(normalized)) {
    return normalized.map((item) => Math.abs(Number(item)) <= 1 ? Math.round(Number(item) * 1000) / 10 : item);
  }
  return typeof normalized === 'number' && Math.abs(normalized) <= 1
    ? Math.round(normalized * 1000) / 10
    : normalized;
}

function pathLabels(value: any): string[] {
  if (Array.isArray(value)) {
    return value.map((node: any) => typeof node === 'string'
      ? node
      : node.label || node.node_id || node.id).filter(Boolean);
  }
  const edges = asArray(value?.edges);
  if (!edges.length) return [];
  const labels: string[] = [];
  edges.forEach((edge: any) => {
    const from = edge.from_node_id || edge.source_node_id;
    const to = edge.to_node_id || edge.target_node_id;
    if (from && labels[labels.length - 1] !== from) labels.push(String(from));
    if (to) labels.push(String(to));
  });
  return labels;
}

function cacheEntries(allocationView: any): any[] {
  const lifecycle = allocationView?.temporal_cache_lifecycle
    || allocationView?.cache_lifecycle
    || allocationView?.temporal_cache;
  if (Array.isArray(lifecycle)) return lifecycle;
  if (Array.isArray(lifecycle?.entries)) return lifecycle.entries.map((entry: any) => ({
    ...entry,
    projection_scope: lifecycle.scope,
    case_specific: lifecycle.case_specific,
  }));
  return lifecycle && typeof lifecycle === 'object' ? [lifecycle] : [];
}

export function DisruptionEvidenceTrace({ allocationView }: ProcurementOperationalTraceProps) {
  const disruptions = asArray(
    allocationView?.disruption_observations
    || allocationView?.disruption_impacts
    || allocationView?.disruptions,
  );
  if (!disruptions.length) return null;
  return (
    <section aria-label="Disruption evidence" data-testid="disruption-evidence-trace" style={{ marginBottom: 12 }}>
      <strong>Disruption evidence and exposure</strong>
      {disruptions.map((item: any, index: number) => {
        const evidence = item.evidence || item.source || item.source_health || {};
        const path = pathLabels(item.dependency_path || item.exposure_path);
        return (
          <div key={item.observation_id || item.id || index} style={{ ...nestedStyle, fontSize: 13 }}>
            <div>{safeText(evidence.source_id || item.source_id, 'Source not recorded')} · revision{' '}
              {safeText(evidence.source_revision || evidence.source_version || item.source_revision)}</div>
            <div>Claim: {humanize(evidence.claim_status || item.claim_status || item.status)} · authority{' '}
              {humanize(item.authority || 'advisory only')}</div>
            {evidence.source_licence && <div>Licence: {safeText(evidence.source_licence)}</div>}
            {evidence.evidence_ref && <div>Evidence reference: {safeText(evidence.evidence_ref)}</div>}
            {path.length > 0
              ? <div>Verified tenant exposure: {path.join(' → ')}</div>
              : <div>No verified tenant exposure path · no commercial change permitted</div>}
          </div>
        );
      })}
    </section>
  );
}

export function TemporalCacheTechnicalTrace({ allocationView }: ProcurementOperationalTraceProps) {
  const entries = cacheEntries(allocationView);
  if (!entries.length) return null;
  return (
    <section aria-label="Temporal cache technical status" data-testid="temporal-cache-technical-trace" style={{ marginBottom: 12 }}>
      <strong>Temporal CacheRAG lifecycle</strong>
      {entries.map((entry: any, index: number) => (
        <div key={entry.cache_key || entry.id || index} style={{ ...nestedStyle, fontSize: 13 }}>
          <div>State: {humanize(entry.status || entry.lifecycle_state)}</div>
          <div>Projection scope: {humanize(entry.projection_scope || 'exact cache key')}</div>
          <div>Cache identity: {safeText(entry.cache_key || entry.namespace || entry.scope, 'redacted')}</div>
          <div>Source version: {safeText(entry.source_version)}</div>
          {entry.evidence_cutoff && <div>Evidence cutoff: {safeText(entry.evidence_cutoff)}</div>}
          {(entry.rebuild_status || entry.rebuild_job_id) && (
            <div>Rebuild: {humanize(entry.rebuild_status || 'queued')} · {safeText(entry.rebuild_job_id, 'job recorded')}</div>
          )}
          <div>Stale generated content served: no</div>
        </div>
      ))}
    </section>
  );
}


export default function ProcurementOperationalTrace({
  allocationView,
}: ProcurementOperationalTraceProps) {
  const summary = allocationView?.summary;
  if (!summary) return null;
  const promise = allocationView?.promise_calculation
    || asArray(allocationView?.promise_calculations)[0]
    || allocationView?.promise_feasibility;

  const disruptions = asArray(
    allocationView.disruption_observations
    || allocationView.disruption_impacts
    || allocationView.disruptions,
  );

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
      <div style={rowStyle}><span>Authority</span><span>Shadow allocation</span></div>
      <div style={rowStyle}>
        <span>Committed / allocated</span>
        <span>{summary.committed_quantity} / {summary.allocated_quantity}</span>
      </div>

      {promise && (
        <section data-testid="proc-promise-feasibility" style={nestedStyle} aria-label="Promise feasibility">
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <strong>Quantity-by-deadline feasibility</strong>
            <span>{humanize(promise.feasibility)}</span>
          </div>
          <div style={rowStyle}>
            <span>Buyer deadline</span>
            <span>{safeText(promise.requested_arrival_at, 'not recorded')}</span>
          </div>
          <div style={rowStyle}>
            <span>Feasible by deadline</span>
            <span>{promise.quantity_by_deadline ?? promise.quantity_confirmed_by_deadline ?? 'unknown'} unit(s)</span>
          </div>
          <div style={rowStyle}>
            <span>Later or unconfirmed</span>
            <span>{promise.remaining_quantity ?? promise.unknown_quantity ?? 'unknown'} unit(s)</span>
          </div>
          {promise.earliest_arrival_range && (
            <div>Arrival range: {safeText(promise.earliest_arrival_range.earliest, 'unknown')}
              {' → '}{safeText(promise.earliest_arrival_range.latest, 'unknown')}</div>
          )}
          {promise.latest_viable_supplier_response_at && (
            <div>Latest viable supplier response: {safeText(promise.latest_viable_supplier_response_at)}</div>
          )}
          {promise.carrier_cutoff_at && <div>Carrier cutoff: {safeText(promise.carrier_cutoff_at)}</div>}
          {asArray(promise.failed_constraints || promise.reason_codes).length > 0 && (
            <div>Failed or unresolved: {asArray(promise.failed_constraints || promise.reason_codes)
              .map(humanize).join(' · ')}</div>
          )}
          <div>
            Calculation {safeText(promise.calculation_version, 'unversioned')}
            {' · '}evaluated {safeText(promise.evaluated_at, 'time not recorded')}
          </div>
          <div>State prevented: {humanize(promise.state_prevented || (
            promise.feasibility === 'met' ? 'none' : 'unsupported full delivery promise'
          ))}</div>
        </section>
      )}
      {allocationView.outbound_contact_schedule && (
        <section data-testid="proc-contact-schedule" style={nestedStyle} aria-label="Supplier contact schedule">
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <strong>Supplier contact schedule</strong>
            <span>{humanize(allocationView.outbound_contact_schedule.queue_state)}</span>
          </div>
          <div style={rowStyle}><span>Channel</span><span>{humanize(allocationView.outbound_contact_schedule.channel)}</span></div>
          <div style={rowStyle}><span>SLA clock</span><span>{humanize(allocationView.outbound_contact_schedule.sla_clock)}</span></div>
          <div style={rowStyle}><span>Transport</span><span>{allocationView.outbound_contact_schedule.transport_eligible
            ? 'eligible now' : 'not executable by email worker'}</span></div>
          <div>Reason: {humanize(allocationView.outbound_contact_schedule.schedule_reason)}</div>
          {allocationView.outbound_contact_schedule.not_before && (
            <div>Not before: {safeText(allocationView.outbound_contact_schedule.not_before)}</div>
          )}
        </section>
      )}
      {allocationView.human_room && (
        <section data-testid="proc-human-room" style={nestedStyle} aria-label="Procurement human room">
          <strong>Human procurement support</strong>
          <div style={rowStyle}><span>Room state</span><span>{humanize(allocationView.human_room.state)}</span></div>
          <div style={rowStyle}><span>Assigned operator</span><span>{safeText(allocationView.human_room.assigned_operator_id, 'not assigned')}</span></div>
          <div>Version {safeText(allocationView.human_room.version, 'not recorded')} Â· tenant and case scoped</div>
        </section>
      )}
      {allocationView.payment_consequence && (
        <section data-testid="proc-payment-consequence" style={nestedStyle} aria-label="Payment consequence">
          <strong>Payment consequence</strong>
          <div style={rowStyle}><span>Plan</span><span>{humanize(allocationView.payment_consequence.plan_type)}</span></div>
          <div style={rowStyle}><span>Status</span><span>{humanize(allocationView.payment_consequence.status)}</span></div>
          <div style={rowStyle}><span>Deposit</span><span>{money(allocationView.payment_consequence.deposit_amount_cents, allocationView.payment_consequence.currency)}</span></div>
          <div style={rowStyle}><span>Balance</span><span>{money(allocationView.payment_consequence.balance_amount_cents, allocationView.payment_consequence.currency)}</span></div>
          {allocationView.payment_consequence.terms_days && <div>Approved terms: Net {allocationView.payment_consequence.terms_days}</div>}
          {allocationView.payment_consequence.authorization_expires_at && (
            <div>Authorization expires: {safeText(allocationView.payment_consequence.authorization_expires_at)}</div>
          )}
          <div>State prevented: {humanize(allocationView.payment_consequence.state_prevented || 'none')}</div>
        </section>
      )}
      <div style={rowStyle}><span>Allocation pressure</span><span>{percent(summary.allocation_pressure)}%</span></div>
      <div style={rowStyle}><span>Oldest demand queue age</span><span>{duration(summary.oldest_queue_age_seconds)}</span></div>
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

      {asArray(allocationView.sourcing_batches).map((batch: any) => (
        <div key={batch.batch_ref} data-testid="proc-consolidated-demand-count" style={rowStyle}>
          <span>{batch.batch_ref}</span>
          <span>{batch.quantity} unit(s) · {batch.child_demand_count} anonymized child demand(s) · {batch.status}</span>
        </div>
      ))}

      {asArray(allocationView.supplier_pressure).map((pressure: any) => (
        <div key={`${pressure.supplier_id}:${pressure.supplier_facility_id}`} data-testid="proc-supplier-pressure" style={nestedStyle}>
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
            {pressure.response_sla?.basis === 'elapsed_compatibility' ? ' · elapsed compatibility clock' : ''}
            {pressure.response_sla?.queue_age_seconds != null
              ? ` · oldest unacknowledged ${duration(pressure.response_sla.queue_age_seconds)}`
              : ''}
          </div>
          {pressure.temporal_response && (
            <div data-testid="proc-temporal-response" style={nestedStyle}>
              <div>
                Supplier calendar: {humanize(pressure.temporal_response.calendar_state)}
                {' · '}SLA clock {humanize(pressure.temporal_response.sla_clock)}
              </div>
              <div>Supplier contact: {transmissionStatus(pressure.temporal_response.transmission_state)}</div>
              {pressure.temporal_response.supplier_local_time && (
                <div>Supplier local time: {safeText(pressure.temporal_response.supplier_local_time)}</div>
              )}
              {pressure.temporal_response.next_open_at && (
                <div>Next operating window: {safeText(pressure.temporal_response.next_open_at)}</div>
              )}
              <div>
                Acknowledgement due: {safeText(pressure.temporal_response.acknowledgement_due_at, 'unknown')}
                {' · '}quote due: {safeText(pressure.temporal_response.quote_due_at, 'unknown')}
              </div>
              <div>
                Calendar {safeText(pressure.temporal_response.calendar_version, 'unversioned')}
                {' · '}policy {safeText(pressure.temporal_response.policy_version, 'unversioned')}
                {' · '}{humanize(pressure.temporal_response.freshness || 'unknown freshness')}
              </div>
              {pressure.temporal_response.reason && (
                <div>Temporal authority: {humanize(pressure.temporal_response.reason)}</div>
              )}
            </div>
          )}
          <div>
            {pressure.source_health?.source_id || 'source unavailable'} ·{' '}
            {pressure.source_health?.source_version || 'version unavailable'} ·{' '}
            {humanize(pressure.source_health?.status)}
          </div>
          <div>New supplier contact: {humanize(pressure.external_contact_authority)}</div>
          {asArray(pressure.reason_codes).length > 0 && (
            <div>Reason: {pressure.reason_codes.map(humanize).join(' · ')}</div>
          )}
        </div>
      ))}

      {asArray(allocationView.sourcing_waves).map((wave: any) => (
        <div key={wave.wave_ref} data-testid="proc-sourcing-wave" style={nestedStyle}>
          <strong>{wave.wave_ref}</strong> · {wave.batch_count} SKU batch(es) · {wave.total_quantity} units
          <div>{wave.supplier_id} / {wave.supplier_facility_id} · {wave.incoterm} · {wave.currency}</div>
          <div>
            Estimated freight saving {money(Math.max(0, Number(wave.estimated_savings_cents || 0)), wave.currency)}
            {' · '}proposal only
          </div>
        </div>
      ))}

      {asArray(allocationView.route_proposals).map((route: any) => {
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

      {asArray(allocationView.recovery_options).map((recovery: any, recoveryIndex: number) => (
        <div key={recovery.batch_ref || `recovery-${recoveryIndex}`} data-testid="proc-recovery-options" style={nestedStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <strong>Grounded recovery options</strong><span>{humanize(recovery.status)}</span>
          </div>
          <div>{safeText(recovery.batch_ref)} · {safeText(recovery.sku, 'SKU not recorded')}</div>
          {asArray(recovery.alternative_suppliers).map((supplier: any) => (
            <div key={`supplier-${supplier.supplier_id}`} data-testid="proc-alternative-supplier" style={rowStyle}>
              <span>Approved alternative · {safeText(supplier.supplier_name, supplier.supplier_id)}</span>
              <span>{humanize(supplier.availability)} · {humanize(supplier.action)}</span>
            </div>
          ))}
          {asArray(recovery.qualified_substitutes).map((substitute: any) => (
            <div key={`substitute-${substitute.sku}`} data-testid="proc-qualified-substitute" style={rowStyle}>
              <span>Qualified substitute · {safeText(substitute.sku)}</span>
              <span>{humanize(substitute.availability)} · buyer consent required</span>
            </div>
          ))}
          {recovery.state_prevented && <div>State prevented: {humanize(recovery.state_prevented)}</div>}
          <div>External action: {humanize(recovery.external_action || 'none')} · confirmation remains required</div>
        </div>
      ))}

      {disruptions.map((disruption: any, disruptionIndex: number) => {
        const source = disruption.source || disruption.source_health || disruption.evidence || {};
        const path = pathLabels(disruption.dependency_path || disruption.exposure_path);
        const baseline = disruption.baseline || disruption.before || {};
        const revised = disruption.revised || disruption.after || {};
        const impact = disruption.impact || {};
        const proposals = asArray(disruption.proposals);
        const payment = disruption.payment_effect || disruption.payment_authorization
          || proposals.find((item: any) => item.type === 'payment_authorization_review') || {};
        const promise = disruption.buyer_promise || disruption.promise_effect
          || proposals.find((item: any) => item.type === 'buyer_promise_review') || {};
        const baselineEta = baseline.eta_days || impact.eta_days?.before;
        const revisedEta = revised.eta_days || impact.eta_days?.proposed;
        const baselineFreight = baseline.freight || baseline.freight_cents
          || impact.freight_cost_minor?.before;
        const revisedFreight = revised.freight || revised.freight_cents
          || impact.freight_cost_minor?.proposed;
        const baselineMargin = baseline.margin_pct ?? impact.contribution_margin?.before;
        const revisedMargin = revised.margin_pct ?? impact.contribution_margin?.proposed;
        return (
          <div
            key={disruption.observation_id || disruption.id || `disruption-${disruptionIndex}`}
            data-testid="proc-active-disruption"
            style={{ ...nestedStyle, borderTopColor: '#f59e0b' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <strong>Active disruption · {humanize(disruption.disruption_type || disruption.type || 'commercial impact')}</strong>
              <span>{humanize(disruption.claim_status || disruption.status)} · {humanize(disruption.severity)}</span>
            </div>
            <div>
              Evidence: {safeText(source.source_id || disruption.source_id, 'source not recorded')}
              {' · '}{safeText(source.source_version || source.source_revision || disruption.source_revision, 'revision not recorded')}
              {' · '}{humanize(source.status || disruption.freshness || 'unknown')}
            </div>
            {path.length > 0 && (
              <div data-testid="proc-disruption-path">Exposed path: {path.join(' → ')}</div>
            )}
            <div data-testid="proc-disruption-impact">
              ETA {impactRange(boundedRange(baselineEta), ' days')} → {impactRange(boundedRange(revisedEta), ' days')}
              {' · '}freight {impactRange(boundedRange(baselineFreight))} → {impactRange(boundedRange(revisedFreight))}
              {' · '}margin {impactRange(marginRange(baselineMargin), '%')} → {impactRange(marginRange(revisedMargin), '%')}
            </div>
            {(promise.status || promise.state || promise.revised_eta || promise.eta_days || promise.affected_count != null) && (
              <div data-testid="proc-revised-promise">
                Buyer promise: {humanize(promise.status || promise.state || 'review required')}
                {promise.affected_count != null ? ` · ${promise.affected_count} affected` : ''}
                {promise.revised_eta
                  ? ` · ${safeText(promise.revised_eta)}`
                  : promise.eta_days ? ` · ETA ${impactRange(boundedRange(promise.eta_days), ' days')}` : ''}
              </div>
            )}
            {(payment.status || payment.state || payment.reason || payment.authorized != null
              || payment.proposed_capture_minor != null) && (
              <div data-testid="proc-payment-effect">
                Payment authorization: {payment.authorized === true
                  ? 'authorized'
                  : humanize(payment.status || payment.state || 'held')}
                {payment.reason ? ` · ${humanize(payment.reason)}` : ''}
                {payment.proposed_capture_minor === 0 ? ' · capture remains 0' : ''}
              </div>
            )}
            {asArray(disruption.contradictions).length > 0 && (
              <div>Contradictions: {asArray(disruption.contradictions).length} · conclusion remains degraded</div>
            )}
            {disruption.state_changed && <div>State changed: {safeText(disruption.state_changed)}</div>}
            <div>State prevented: {humanize(safeText(
              disruption.state_prevented,
              'external evidence cannot directly change allocation, payment, price or supplier contact',
            ))}</div>
          </div>
        );
      })}

      {(() => {
        const segments = asArray(allocationView.demands).reduce((counts: Record<string, number>, demand: any) => {
          const raw = String(demand.commerce_mode || demand.buyer_type || demand.account_type || '').toLowerCase();
          const key = raw.includes('b2b') || raw.includes('business')
            ? 'B2B'
            : raw.includes('b2c') || raw.includes('consumer') ? 'B2C' : '';
          if (key) counts[key] = (counts[key] || 0) + 1;
          return counts;
        }, {});
        const labels = Object.entries(segments).map(([key, count]) => `${key} ${count}`);
        return labels.length ? (
          <div data-testid="proc-buyer-segments" style={nestedStyle}>
            <strong>Demand authority by channel</strong>
            <div>{labels.join(' · ')} · buyer identities hidden</div>
            <div>B2C and B2B commitments share ATP only through sealed allocation policy.</div>
          </div>
        ) : null;
      })()}

      {cacheEntries(allocationView).map((entry: any, entryIndex: number) => {
        const state = String(entry.status || entry.lifecycle_state || 'unknown').toLowerCase();
        return (
          <div key={entry.cache_key || entry.id || `cache-${entryIndex}`} data-testid="proc-temporal-cache" style={nestedStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <strong>Temporal CacheRAG</strong><span>{humanize(state)}</span>
            </div>
            <div>Scope: {humanize(entry.projection_scope || entry.scope || entry.namespace || 'redacted')}</div>
            {entry.case_specific === false && <div>Tenant-wide operator summary; not evidence for this case.</div>}
            {entry.reason && <div>Reason: {humanize(entry.reason)}</div>}
            {(entry.source_version || entry.evidence_cutoff) && (
              <div>
                Evidence version: {safeText(entry.source_version)}
                {entry.evidence_cutoff ? ` · cutoff ${safeText(entry.evidence_cutoff)}` : ''}
              </div>
            )}
            {(entry.rebuild_job_id || entry.rebuild_status) && (
              <div>Rebuild: {humanize(entry.rebuild_status || 'queued')} · {safeText(entry.rebuild_job_id, 'job recorded')}</div>
            )}
            <div>Generated narration: {['fresh', 'rebuilt'].includes(state)
              ? 'available'
              : 'unavailable while evidence is stale or rebuilding'}</div>
            <div>Operational allocation facts: authoritative live read</div>
          </div>
        );
      })}
    </section>
  );
}
