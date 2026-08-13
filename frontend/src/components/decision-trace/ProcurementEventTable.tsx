import { Fragment, useState } from 'react';

import { explainProcEvent } from '../../lib/procEventExplain';

type Props = {
  events: any[];
  classNames: Record<string, string>;
  componentSource: (event: any) => string;
  displayEventType: (event: any) => string;
  eventSummary: (event: any) => string;
};

export default function ProcurementEventTable({
  events, classNames, componentSource, displayEventType, eventSummary,
}: Props) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  if (!events.length) return null;
  return (
    <table className={classNames.table} data-testid="procurement-event-table">
      <thead><tr><th></th><th>Component</th><th>Event</th><th>Mode</th><th>Detail</th><th>When</th></tr></thead>
      <tbody>
        {events.map((event, index) => {
          const payload: any = event?.payload || {};
          const transfers = Array.isArray(payload.transfer_plan) ? payload.transfer_plan : [];
          const detail = [
            payload.sku && `SKU ${payload.sku}`,
            payload.order_qty != null && `qty ${payload.order_qty}`,
            payload.in_stock != null && `in-stock ${payload.in_stock}`,
            payload.shortfall != null && `shortfall ${payload.shortfall}`,
            payload.now_qty != null && `ship-now ${payload.now_qty}`,
            payload.later_qty != null && `follow ${payload.later_qty}`,
            payload.eta_days != null && `ETA ~${payload.eta_days}d`,
            transfers.length > 0 && `transfer ${transfers.map((row: any) => `${row.qty}@${row.from_location}`).join(', ')}`,
            payload.status && `status ${payload.status}`,
            Array.isArray(payload.types) && payload.types.length > 0 && `options: ${payload.types.join(', ')}`,
            payload.count != null && `${payload.count} alternatives`,
            payload.channel && `channel: ${payload.channel}`,
            payload.requires_human === true && 'HUMAN-only outreach',
            payload.integration_kind && `→ ${String(payload.integration_kind).toUpperCase()} integration`,
            payload.channel && payload.agent_may_draft === true && 'agent drafts · human sends',
            payload.case_id && `case ${String(payload.case_id).slice(0, 8)}`,
          ].filter(Boolean).join(' · ');
          const execution = String(payload.execution || '');
          const modelAssisted = execution.startsWith('llm');
          const when = String(event?.created_at || '').replace('T', ' ').slice(11, 19);
          const isOpen = Boolean(expanded[index]);
          const drill = Object.fromEntries(Object.entries(payload).filter(([key]) => !key.startsWith('_')));
          const explanation = explainProcEvent(displayEventType(event), payload);
          return (
            <Fragment key={event?.id || index}>
              <tr data-testid={`proc-event-row-${index}`} style={{ cursor: 'pointer' }}
                  onClick={() => setExpanded(previous => ({ ...previous, [index]: !previous[index] }))}
                  title="Click to inspect this step's full recorded payload">
                <td style={{ width: 18, color: '#9ca3af' }}>{isOpen ? '▾' : '▸'}</td>
                <td title={`Recorded producer: ${event?.source_id || 'unknown'}`}>{componentSource(event)}</td>
                <td>{displayEventType(event)}</td>
                <td>{execution ? (
                  <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 8,
                    background: modelAssisted ? '#f3e8ff' : '#f3f4f6',
                    color: modelAssisted ? '#7e22ce' : '#374151',
                    border: `1px solid ${modelAssisted ? '#d8b4fe' : '#d1d5db'}` }}>
                    {modelAssisted ? execution : 'deterministic'}
                  </span>
                ) : <span style={{ color: '#d1d5db' }}>—</span>}</td>
                <td>{detail || eventSummary(event)}</td>
                <td className={classNames.mono} style={{ fontSize: 11, whiteSpace: 'nowrap' }}>{when || '—'}</td>
              </tr>
              {isOpen && (
                <tr data-testid={`proc-event-drill-${index}`}>
                  <td></td>
                  <td colSpan={5}>
                    {explanation && (
                      <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 6,
                        padding: '6px 10px', margin: '4px 0', fontSize: 12 }}>
                        <div><strong>What happened:</strong> {explanation.what}</div>
                        {explanation.why && <div style={{ marginTop: 2 }}><strong>Why:</strong> {explanation.why}</div>}
                      </div>
                    )}
                    <details style={{ margin: '4px 0' }}>
                      <summary style={{ cursor: 'pointer', fontSize: 11, color: '#6b7280' }}>Raw recorded payload (evidence)</summary>
                      <pre style={{ whiteSpace: 'pre-wrap', background: '#f9fafb', border: '1px solid #e5e7eb',
                        borderRadius: 6, padding: 8, margin: '4px 0', maxHeight: 220, overflow: 'auto',
                        fontSize: 11 }}>{JSON.stringify(drill, null, 2)}</pre>
                    </details>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
