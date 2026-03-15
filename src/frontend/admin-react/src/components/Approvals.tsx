import React, { useEffect, useState } from 'react';
import { approveApproval, fetchApprovals, rejectApproval, type ApprovalItem } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };
type OperatorMetricSnapshot = {
  catalogProfileCacheHit?: boolean | null;
  catalogProfileMs?: number | null;
  routeTotalMs?: number | null;
  ollamaSummaryMs?: number | null;
  traceId?: string | null;
  source?: string | null;
  recordedAt?: string | null;
};

export function Approvals({ role }: Props) {
  const [rows, setRows] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightApprovalId, setHighlightApprovalId] = useState<string | null>(null);
  const [operatorMetrics, setOperatorMetrics] = useState<OperatorMetricSnapshot | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchApprovals().then(setRows).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const approvalId = params.get('approval_id');
      if (approvalId) setHighlightApprovalId(approvalId);
    } catch {}
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const refreshMetrics = () => {
      try {
        const raw = localStorage.getItem('shopsquire_operator_metrics');
        setOperatorMetrics(raw ? JSON.parse(raw) as OperatorMetricSnapshot : null);
      } catch {
        setOperatorMetrics(null);
      }
    };
    refreshMetrics();
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'shopsquire_operator_metrics') refreshMetrics();
    };
    window.addEventListener('storage', onStorage);
    const timer = window.setInterval(refreshMetrics, 5000);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.clearInterval(timer);
    };
  }, []);

  const bundleRows = rows.filter((row) => row.capability === 'bundle_discount');
  const genericRows = rows.filter((row) => row.capability !== 'bundle_discount');

  return (
    <div className="stagger">
      <div className="grid-2">
        <div className="card">
          <h3>Pending Queue</h3>
          <div className="metric">{rows.length}</div>
          <div className="badge">Auto-approve threshold: $250</div>
        </div>
        <div className="card">
          <h3>Guardrail Summary</h3>
          <div className="list">
            <div className="list-item"><div>Bundle discounts</div><strong>{bundleRows.length} waiting</strong></div>
            <div className="list-item"><div>Refund requests</div><strong>1 waiting</strong></div>
            <div className="list-item"><div>Manual review rate</div><strong>4.8%</strong></div>
            <div className="list-item"><div>Catalog cache</div><strong>{operatorMetrics?.catalogProfileCacheHit == null ? '--' : operatorMetrics.catalogProfileCacheHit ? 'hit' : 'miss'}</strong></div>
            <div className="list-item"><div>Catalog profile</div><strong>{operatorMetrics?.catalogProfileMs == null ? '--' : `${Math.round(Number(operatorMetrics.catalogProfileMs) || 0)}ms`}</strong></div>
            <div className="list-item"><div>Ollama summary</div><strong>{operatorMetrics?.ollamaSummaryMs == null ? '--' : `${Math.round(Number(operatorMetrics.ollamaSummaryMs) || 0)}ms`}</strong></div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Bundle Discount Reviews</h3>
        <div className="page-sub">20% tier requires human approval. 15% tier remains automatic.</div>
        {!bundleRows.length && <div className="page-sub">No pending bundle discount reviews.</div>}
        {bundleRows.map((a) => {
          const payload = a.payload || {};
          const items = Array.isArray(payload.items) ? payload.items : [];
          const pct = Number(payload.requested_discount_percent || 0) * 100;
          const subtotal = Number(payload.subtotal_cents || 0) / 100;
          const est = Number(payload.estimated_final_total_cents || 0) / 100;
          const laptop = Number(payload.laptop_subtotal_cents || 0) / 100;
          const accessories = Number(payload.accessories_subtotal_cents || 0) / 100;
          return (
            <div key={a.id} className="card" style={{ marginTop: 12, background: a.id === highlightApprovalId ? '#fff3d6' : '#fffaf4', border: a.id === highlightApprovalId ? '1px solid #e0a400' : undefined }}>
              <div className="list-item">
                <div>
                  <strong>{pct.toFixed(0)}% laptop bundle review</strong>
                  <div className="page-sub">Cart {payload.cart_id || '-'} · User {payload.uid || '-'}</div>
                </div>
                <div className="badge">{a.status}</div>
              </div>
              <div className="grid-2" style={{ marginTop: 10 }}>
                <div className="list">
                  <div className="list-item"><div>Laptop subtotal</div><strong>${laptop.toLocaleString()}</strong></div>
                  <div className="list-item"><div>Accessories</div><strong>${accessories.toLocaleString()}</strong></div>
                  <div className="list-item"><div>Cart subtotal</div><strong>${subtotal.toLocaleString()}</strong></div>
                  <div className="list-item"><div>Estimated total after approval</div><strong>${est.toLocaleString()}</strong></div>
                </div>
                <div>
                  <div className="page-sub">Items in request</div>
                  <div className="list">
                    {items.map((item: any, idx: number) => (
                      <div key={`${a.id}-${idx}`} className="list-item">
                        <div>{item.name || item.sku}</div>
                        <strong>{item.quantity || 1} x ${(Number(item.price_cents || 0) / 100).toLocaleString()}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
                <button className="btn" onClick={async () => { await approveApproval(a.id); load(); }}>Approve 20%</button>
                <button className="btn secondary" onClick={async () => { await rejectApproval(a.id); load(); }}>Reject to 15%</button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Approval Requests</h3>
        {loading && <div className="page-sub">Loading...</div>}
        {error && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {error}</div>}
        <table className="table">
          <thead>
            <tr>
              <th>Capability</th>
              <th>Reason</th>
              <th>Payload</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {genericRows.map(a => (
              <tr key={a.id}>
                <td>{a.capability}</td>
                <td>{a.reason || '-'}</td>
                <td><code>{JSON.stringify(a.payload)}</code></td>
                <td>{a.status}</td>
                <td>
                  <button className="btn" onClick={async () => { await approveApproval(a.id); load(); }}>Approve</button>
                  <button className="btn secondary" onClick={async () => { await rejectApproval(a.id); load(); }}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {role === 'owner' && (
        <div className="callout" style={{ marginTop: 12 }}>
          Owner-only: raise approval thresholds and configure escalation routing.
        </div>
      )}
    </div>
  );
}
