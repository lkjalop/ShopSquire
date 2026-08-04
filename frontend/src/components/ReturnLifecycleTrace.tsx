type ReturnEvent = {
  event_type?: string;
  payload?: Record<string, any>;
  timestamp?: string;
};

const LABELS: Record<string, string> = {
  received: 'Claim received', evidence_pending: 'Evidence review pending',
  needs_info: 'Buyer information required', under_review: 'Under human review',
  approved: 'Return approved', repair_authorized: 'Repair authorized',
  in_transit: 'Item in transit', received_at_facility: 'Received at facility',
  repair_in_progress: 'Repair in progress', repaired: 'Repair completed',
  replacement_sent: 'Replacement sent', refund_pending: 'Refund pending authorization',
  refunded: 'Refund recorded', rejected: 'Claim rejected', closed: 'Case closed',
};

export function returnLifecycleProjection(events: ReturnEvent[]) {
  const relevant = (events || []).filter((event) =>
    String(event.event_type || '').toLowerCase().includes('return_claim'));
  if (!relevant.length) return null;
  const payload = relevant[relevant.length - 1].payload || {};
  const status = String(payload.status || payload.to_status || 'evidence_pending');
  return {
    claimId: payload.claim_id || null,
    status,
    orderVerification: String(payload.order_verification_status || 'source_unavailable'),
    evidenceCount: Number(payload.evidence_count || 0),
    evidenceStatus: String(payload.evidence_status || payload.security_status || 'pending'),
    authority: String(payload.authority || 'observation_only'),
    prevented: Boolean(payload.commercial_action_prevented),
    timeline: relevant.map((event) => ({
      status: String(event.payload?.status || event.payload?.to_status || 'evidence_pending'),
      timestamp: event.timestamp || event.payload?.recorded_at || null,
      eventType: String(event.event_type || 'return_claim_event'),
    })),
  };
}

export default function ReturnLifecycleTrace({ events }: { events: ReturnEvent[] }) {
  const view = returnLifecycleProjection(events);
  if (!view) return null;
  const verification = view.orderVerification === 'found'
    ? 'Authenticated order matched'
    : view.orderVerification === 'not_found'
      ? 'Order reference required from buyer'
      : 'Order service unavailable — retrying; buyer is not penalized';
  return (
    <section data-testid="return-lifecycle-trace" aria-label="Return and repair journey"
      style={{ border: '1px solid #94a3b8', borderRadius: 10, padding: 12, marginBottom: 12, background: '#f8fafc' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <strong>After-sales case · {LABELS[view.status] || view.status.replace(/_/g, ' ')}</strong>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#475569' }}>{view.authority.replace(/_/g, ' ')}</span>
      </div>
      <div style={{ marginTop: 8, display: 'grid', gap: 5, fontSize: 13 }}>
        <div><strong>Order authority:</strong> {verification}</div>
        <div><strong>Evidence:</strong> {view.evidenceCount || 'Uploaded'} · {view.evidenceStatus.replace(/_/g, ' ')}</div>
        {view.prevented && <div style={{ color: '#92400e', fontWeight: 700 }}>
          State prevented: no refund, replacement or repair authorization while evidence is pending.
        </div>}
      </div>
      <ol style={{ margin: '10px 0 0', paddingLeft: 20, fontSize: 12, color: '#475569' }}>
        {view.timeline.map((entry, index) => <li key={`${entry.eventType}-${index}`}>
          {LABELS[entry.status] || entry.status.replace(/_/g, ' ')}
          {entry.timestamp ? ` · ${new Date(entry.timestamp).toLocaleString()}` : ''}
        </li>)}
      </ol>
    </section>
  );
}
