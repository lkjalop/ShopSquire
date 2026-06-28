// WS-D observability panel: the autonomous-RFQ-send decision trail + the live enabled/killed toggle and
// transport preflight. This is the visibility that makes turning autonomy on responsible — what auto-sent,
// what escalated and why, whether real sending is wired. Read-only; polls the operator audit endpoint.
import React, { useCallback, useEffect, useState } from 'react';
import { fcAutonomousAudit, type AutonomousAudit } from '../../api';

const badge = (text: string, bg: string, fg: string) => (
  <span style={{ marginLeft: 8, padding: '2px 8px', background: bg, color: fg, borderRadius: 4,
                 fontSize: 12, fontWeight: 700 }}>{text}</span>
);

export function AutonomyAudit() {
  const [data, setData] = useState<AutonomousAudit | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    fcAutonomousAudit(50).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(e?.message || 'load failed'));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (err) return <p role="alert" style={{ color: 'crimson' }}>Autonomy audit: {err}</p>;
  if (!data) return null;

  const t = data.transport;
  const transportWarn = t && t.mode === 'smtp' && !t.configured;

  return (
    <details data-testid="autonomy-audit" style={{ marginBottom: 12, padding: '8px 12px', borderRadius: 8,
             border: '1px solid #e5e7eb', background: '#f9fafb' }}>
      <summary style={{ fontWeight: 700, cursor: 'pointer' }}>
        Autonomous RFQ send
        {data.enabled
          ? badge('AUTONOMY ON', '#dcfce7', '#166534')
          : badge('AUTONOMY OFF', '#e5e7eb', '#374151')}
        {data.killed && badge('KILL SWITCH', '#fee2e2', '#991b1b')}
        {t && badge(`transport: ${t.mode}${t.transmits ? ' (sends)' : ' (sandbox)'}`,
                    transportWarn ? '#fef3c7' : '#e0e7ff', transportWarn ? '#92400e' : '#3730a3')}
      </summary>

      <div style={{ display: 'flex', gap: 16, margin: '8px 0', flexWrap: 'wrap' }}>
        <span data-testid="autonomy-sent">Auto-sent: <strong>{data.summary.sent}</strong></span>
        <span data-testid="autonomy-escalated">Escalated: <strong>{data.summary.escalated}</strong></span>
        <button className="btn secondary" style={{ marginLeft: 'auto' }} onClick={load}>Refresh</button>
      </div>

      {transportWarn && (
        <div role="alert" style={{ margin: '4px 0', padding: '6px 8px', borderRadius: 6, background: '#fef3c7',
             color: '#92400e' }}>
          ⚠ SMTP selected but not configured (missing {t!.missing.join(', ')}). Enabling autonomy now would
          fail every send — set SMTP_HOST/SMTP_SENDER first.
        </div>
      )}

      {Object.keys(data.summary.by_reason).length > 0 && (
        <div style={{ fontSize: 13, marginBottom: 6 }}>
          Escalation reasons: {Object.entries(data.summary.by_reason)
            .map(([k, v]) => `${k} (${v})`).join(' · ')}
        </div>
      )}

      <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', color: '#6b7280' }}>
            <th>when</th><th>decision</th><th>reason</th><th>case</th><th>conf</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i} style={{ borderTop: '1px solid #eee' }}>
              <td>{r.created_at || '—'}</td>
              <td style={{ color: r.decision === 'allow' ? '#166534' : '#92400e', fontWeight: 600 }}>
                {r.decision === 'allow' ? 'sent' : r.decision}
              </td>
              <td>{r.reason || '—'}</td>
              <td title={r.target || ''}>{(r.target || '').slice(0, 8) || '—'}</td>
              <td>{r.confidence ? r.confidence.toFixed(2) : '—'}</td>
            </tr>
          ))}
          {data.rows.length === 0 && (
            <tr><td colSpan={5} style={{ color: '#6b7280', padding: 6 }}>No autonomous decisions recorded yet.</td></tr>
          )}
        </tbody>
      </table>
    </details>
  );
}

export default AutonomyAudit;
