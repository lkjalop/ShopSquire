import React, { useEffect, useMemo, useState } from 'react';
import {
  fetchGrcFingerprintAlerts,
  fetchGrcReport,
  fetchGrcRiskRegister,
  fetchGrcTrends,
  runGrcFingerprintIngest,
  updateGrcFingerprintAlertStatus,
} from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

const API_BASE = (import.meta.env.VITE_API_BASE as string) || window.location.origin;

function apiKey(): string {
  return (import.meta.env.VITE_API_KEY as string) || '';
}

export function GRC({ role }: Props) {
  const [days, setDays] = useState(30);
  const [risk, setRisk] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [trends, setTrends] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>('open');
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [runInfo, setRunInfo] = useState<any>(null);
  const [noteById, setNoteById] = useState<Record<string, string>>({});

  const load = () => {
    setLoading(true);
    Promise.all([
      fetchGrcRiskRegister(days),
      fetchGrcReport(days),
      fetchGrcTrends(days),
      fetchGrcFingerprintAlerts({ status: statusFilter || undefined, severity: severityFilter || undefined, limit: 200 }),
    ])
      .then(([rr, rep, tr, al]) => {
        setRisk(rr);
        setReport(rep);
        setTrends(tr);
        setAlerts(al.items || []);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, statusFilter, severityFilter]);

  const domainRows = risk?.domains || [];
  const controls = report?.controls || [];

  const trendRows = useMemo(() => {
    const s = trends?.series || {};
    return Object.keys(s).map((k) => {
      const vals = (s[k] || []).map((x: any) => Number(x.count || 0));
      const max = Math.max(...vals, 1);
      return { key: k, points: s[k] || [], max };
    });
  }, [trends]);

  const exportReport = async (ext: 'csv' | 'md' | 'pdf') => {
    const url = `${API_BASE.replace(/\/$/, '')}/api/v1/admin/grc/report/export.${ext}?days=${days}`;
    const headers: Record<string, string> = {};
    const k = apiKey();
    if (k) headers['x-api-key'] = k;
    const r = await fetch(url, { headers, credentials: 'include' });
    if (!r.ok) return;
    const blob = await r.blob();
    const dl = document.createElement('a');
    dl.href = URL.createObjectURL(blob);
    dl.download = `shopsquire-grc-report-${days}d.${ext}`;
    dl.click();
    URL.revokeObjectURL(dl.href);
  };

  if (role !== 'owner' && role !== 'developer') {
    return (
      <div className="panel">
        <strong>GRC</strong>
        <div className="page-sub">Owner/Developer only.</div>
      </div>
    );
  }

  return (
    <div className="stagger">
      <div className="panel">
        <strong>GRC Consultant Console</strong>
        <div className="page-sub">Adaptive risk register, control mapping, fingerprint alerts, and audit-ready exports.</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value, 10))}>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
          <button className="btn secondary" onClick={load}>Refresh</button>
          <button
            className="btn"
            onClick={() => {
              runGrcFingerprintIngest().then((res) => {
                setRunInfo(res);
                load();
              });
            }}
          >
            Run Fingerprint Ingestion
          </button>
          <button className="btn secondary" onClick={() => exportReport('csv')}>Export CSV</button>
          <button className="btn secondary" onClick={() => exportReport('md')}>Export MD</button>
          <button className="btn secondary" onClick={() => exportReport('pdf')}>Export PDF</button>
        </div>
        {runInfo && (
          <div className="page-sub" style={{ marginTop: 8 }}>
            Ingestion: scans={runInfo.scans || 0}, alerts={runInfo.alerts_created || 0}
          </div>
        )}
        {loading && <div className="page-sub" style={{ marginTop: 8 }}>Loading...</div>}
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        {domainRows.map((d: any) => (
          <div className="card" key={d.domain}>
            <h3>{d.domain}</h3>
            <div className="metric">{d.risk_score}</div>
            <div className="badge">{d.risk_band}</div>
            <div className="page-sub" style={{ marginTop: 8 }}>
              {Object.entries(d.signals || {})
                .map(([k, v]) => `${k}: ${v}`)
                .join(' | ')}
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Control Map and Evidence Links</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Control</th>
              <th>Status</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {controls.map((c: any) => (
              <tr key={c.control_id}>
                <td>{c.control_id}</td>
                <td>{c.status}</td>
                <td>
                  <a href={c.evidence_link} target="_blank" rel="noreferrer">{c.evidence_link}</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Trend Charts</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
          {trendRows.map((row: any) => (
            <div className="mini" key={row.key}>
              <div className="page-sub">{row.key}</div>
              <div className="bar-chart" style={{ height: 120, gridTemplateColumns: `repeat(${row.points.length || 1}, 1fr)` }}>
                {(row.points || []).map((p: any) => {
                  const h = Math.max(6, ((Number(p.count || 0) / row.max) * 100));
                  return (
                    <div className="bar" key={`${row.key}-${p.day}`}>
                      <div className="bar-fill" style={{ height: `${h}%` }} />
                      <span>{String(p.day).slice(5)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Fingerprint Alerts and Remediation Workflow</h3>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All Status</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="resolved">Resolved</option>
            <option value="ignored">Ignored</option>
          </select>
          <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
            <option value="">All Severity</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
        </div>
        <table className="table" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>Alert</th>
              <th>Target</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id}>
                <td>
                  {a.alert_type}
                  <div className="page-sub">{a.reason}</div>
                </td>
                <td>{a.target}</td>
                <td>{a.severity}</td>
                <td>{a.status}</td>
                <td>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button
                      className="btn secondary"
                      onClick={() => updateGrcFingerprintAlertStatus(a.id, 'in_progress').then(load)}
                    >
                      Start
                    </button>
                    <button
                      className="btn secondary"
                      onClick={() => updateGrcFingerprintAlertStatus(a.id, 'resolved', noteById[a.id] || '').then(load)}
                    >
                      Resolve
                    </button>
                    <input
                      className="modal-input"
                      style={{ width: 180, marginTop: 0 }}
                      value={noteById[a.id] || ''}
                      placeholder="remediation note"
                      onChange={(e) => setNoteById((prev) => ({ ...prev, [a.id]: e.target.value }))}
                    />
                  </div>
                </td>
              </tr>
            ))}
            {alerts.length === 0 && (
              <tr>
                <td colSpan={5}>No alerts for current filter.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
