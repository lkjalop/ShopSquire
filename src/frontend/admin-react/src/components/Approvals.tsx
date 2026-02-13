import React, { useEffect, useState } from 'react';
import { approveApproval, fetchApprovals, rejectApproval, type ApprovalItem } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function Approvals({ role }: Props) {
  const [rows, setRows] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchApprovals().then(setRows).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

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
            <div className="list-item"><div>Price overrides</div><strong>3 waiting</strong></div>
            <div className="list-item"><div>Refund requests</div><strong>1 waiting</strong></div>
            <div className="list-item"><div>Manual review rate</div><strong>4.8%</strong></div>
          </div>
        </div>
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
            {rows.map(a => (
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
