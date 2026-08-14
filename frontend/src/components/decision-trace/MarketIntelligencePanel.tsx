import type { ReactNode } from 'react';

type MarketEvent = { payload?: Record<string, any> };

export default function MarketIntelligencePanel({
  events,
  behaviorEvents = [],
  dependencyEvidence,
  classNames,
  humanize,
  formatTime,
}: {
  events: MarketEvent[];
  behaviorEvents?: MarketEvent[];
  dependencyEvidence?: ReactNode;
  classNames: { summaryPane: string; sectionTitle: string; empty: string; kvRow: string };
  humanize: (value: unknown) => string;
  formatTime: (value: unknown) => string;
}) {
  return (
    <div className={classNames.summaryPane} data-testid="market-intelligence-tab">
      <h3 style={{ marginTop: 0 }}>Market Intelligence</h3>
      <p style={{ color: '#6b7280', marginTop: 0 }}>
        Transaction-derived demand and stock evidence scoped to products shown in this decision.
        Commercial economics and action controls are available only in the operator console.
      </p>
      {dependencyEvidence && (
        <>
          <div className={classNames.sectionTitle}>Dependency paths supporting this finding</div>
          {dependencyEvidence}
        </>
      )}
      {behaviorEvents.map((event, index) => {
        const item = event.payload || {};
        return (
          <div key={`cohort-${index}`} data-testid="cohort-behavior-projection"
               style={{ border: '1px solid #fde68a', background: '#fffbeb', borderRadius: 8, padding: 12, marginBottom: 10 }}>
            <strong>Aggregate buyer behavior</strong>
            <div className={classNames.kvRow}><span>Status</span><span>{humanize(item.status)}</span></div>
            <div className={classNames.kvRow}><span>Privacy</span><span>Individual clicks, hovers, carts, users, and cases are hidden</span></div>
            {item.status === 'aggregated' && Array.isArray(item.measurements) && item.measurements.map((metric: any) => (
              <div className={classNames.kvRow} key={metric.metric}>
                <span>{humanize(metric.metric)}</span>
                <span>{metric.value == null ? 'not verified' : `${Math.round(Number(metric.value) * 100)}%`} · cohort {item.sample_size}</span>
              </div>
            ))}
          </div>
        );
      })}
      {events.length === 0 ? (
        <div className={classNames.empty}>No scoped market projection was recorded for this decision.</div>
      ) : events.map((event, index) => {
        const item = event.payload || {};
        return (
          <div key={`${item.sku || 'projection'}-${index}`} data-testid={`market-projection-${item.sku}`}
               style={{ border: '1px solid #bfdbfe', background: '#eff6ff', borderRadius: 8, padding: 12, marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontWeight: 700 }}>
              <span>{item.sku}</span><span>rank {item.rank ?? '—'}</span>
            </div>
            <div className={classNames.kvRow}><span>Demand</span><span>{humanize(item.demand_trend)} · {item.forecast_units_30d ?? 'not verified'} units / 30d</span></div>
            <div className={classNames.kvRow}><span>Inventory</span><span>{item.stock_on_hand ?? 'not disclosed'} on hand · DSI {item.velocity_dsi_days ?? 'not verified'} days</span></div>
            <div className={classNames.kvRow}><span>Bulk frequency</span><span>{item.bulk_frequency
              ? `${item.bulk_frequency.bulk_order_count} cases / ${item.bulk_frequency.window_days ?? 90}d`
              : humanize(item.bulk_frequency_state || 'not_collected')}</span></div>
            <div className={classNames.kvRow}><span>Evidence</span><span>{humanize(item.status || item.confidence)} · as of {formatTime(item.as_of)}</span></div>
            <div className={classNames.kvRow}><span>Sources</span><span>{humanize(item.source_status?.sales)} sales · {humanize(item.source_status?.inventory)} inventory</span></div>
            <div className={classNames.kvRow}><span>Observation truth</span><span>{humanize(item.measurement_truth?.sales)} sales · {humanize(item.measurement_truth?.inventory)} inventory</span></div>
            <div className={classNames.kvRow}><span>Authority</span><span>Advisory evidence only · deterministic gates authorize actions</span></div>
            {Array.isArray(item.metrics) && item.metrics.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ cursor: 'pointer', fontSize: 12, color: '#4b5563' }}>Metric provenance</summary>
                {item.metrics.map((metric: any, metricIndex: number) => (
                  <div key={`${metric.metric || 'metric'}-${metricIndex}`} style={{ borderTop: '1px solid #dbeafe', paddingTop: 6, marginTop: 6 }}>
                    <div className={classNames.kvRow}><span>{humanize(metric.metric)}</span><span>{metric.value ?? 'unavailable'} {metric.unit || ''}</span></div>
                    <div className={classNames.kvRow}><span>Status</span><span>{humanize(metric.status)} · confidence {metric.confidence == null ? 'not recorded' : `${Math.round(Number(metric.confidence) * 100)}%`}</span></div>
                    <div className={classNames.kvRow}><span>Lineage</span><span>{Array.isArray(metric.provenance_chain) && metric.provenance_chain.length ? metric.provenance_chain.join(' → ') : 'not supplied'}</span></div>
                  </div>
                ))}
              </details>
            )}
          </div>
        );
      })}
    </div>
  );
}
