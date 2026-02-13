import React, { useEffect, useMemo, useState } from 'react';
import { fetchComplianceOverview, fetchComplianceEvidence, fetchComplianceLiveFeed } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function Compliance({ role }: Props) {
  const [days, setDays] = useState(7);
  const [overview, setOverview] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [live, setLive] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [controlFilter, setControlFilter] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([fetchComplianceOverview(days), fetchComplianceEvidence(days), fetchComplianceLiveFeed(30)])
      .then(([o, e, l]) => {
        setOverview(o);
        setEvidence(e);
        setLive(l.items || []);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [days]);

  if (role !== 'owner') {
    return (
      <div className="panel">
        <strong>Compliance</strong>
        <div className="page-sub">Owner-only: governance evidence and compliance mapping.</div>
      </div>
    );
  }

  const frameworks = overview?.frameworks || {};
  const summary = overview?.summary || {};
  const evidenceCounts = overview?.evidence_counts || {};
  const controlIndex = Object.entries(frameworks).flatMap(([fw, data]: any) =>
    (data.controls || []).map((c: any) => ({
      key: `${fw}:${c.id}`,
      framework: fw,
      id: c.id,
      name: c.name,
      signals: c.signals || [],
    }))
  );

  const matchesControl = (item: any, controlSignals: string[]) => {
    if (!controlSignals.length) return true;
    if (item.type === 'security') {
      const analysis = item.details?.analysis || {};
      if (controlSignals.includes('security_events')) return true;
      if (controlSignals.includes('mitre_atlas') && (analysis.mitre_atlas || []).length) return true;
      if (controlSignals.includes('owasp_llm_top10') && (analysis.owasp_llm_top10 || []).length) return true;
      if (controlSignals.includes('kev') && (analysis.kev_ids || []).length) return true;
      if (controlSignals.includes('stride') && analysis.stride_score != null) return true;
      if (controlSignals.includes('dread') && analysis.dread_avg != null) return true;
      if (controlSignals.includes('cvss') && analysis.cvss_score != null) return true;
    }
    if (item.type === 'decision') {
      if (controlSignals.includes('decision_logs')) return true;
      if (controlSignals.includes('approvals') && item.approval_required) return true;
    }
    if (item.type === 'incident') {
      if (controlSignals.includes('incidents')) return true;
    }
    return false;
  };

  const evidenceList = useMemo(() => {
    const list: any[] = [];
    if (evidence?.security_events) {
      evidence.security_events.forEach((e: any) => list.push({ ...e, type: 'security' }));
    }
    if (evidence?.decision_logs) {
      evidence.decision_logs.forEach((d: any) => list.push({ ...d, type: 'decision' }));
    }
    if (evidence?.incidents) {
      evidence.incidents.forEach((i: any) => list.push({ ...i, type: 'incident' }));
    }
    if (!controlFilter) return list;
    const control = controlIndex.find((c: any) => c.key === controlFilter);
    if (!control) return list;
    return list.filter((item) => matchesControl(item, control.signals));
  }, [evidence, controlFilter, controlIndex]);

  return (
    <div className="stagger">
      <div className="panel">
        <strong>Compliance Overview</strong>
        <div className="page-sub">ISO27001, PCI-DSS, ISO42001, NIST AI RMF, EU AI Act</div>
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="page-sub">Range</span>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value, 10))}>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
          <button className="btn secondary" onClick={load}>Refresh</button>
        </div>
        {loading && <div className="page-sub" style={{ marginTop: 8 }}>Loading...</div>}
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        {Object.keys(summary).map((k) => (
          <div className="card" key={k}>
            <h3>{k.toUpperCase()}</h3>
            <div className="metric">{summary[k].covered}/{summary[k].total} controls covered</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Evidence Counts</h3>
        <div className="page-sub">Security events, decision logs, incidents, approvals</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginTop: 8 }}>
          {Object.keys(evidenceCounts).map((k) => (
            <div className="mini" key={k}>
              <div className="metric">{evidenceCounts[k]}</div>
              <div className="page-sub">{k.replace('_', ' ')}</div>
            </div>
          ))}
        </div>
        <div className="bar-chart" style={{ marginTop: 12 }}>
          {Object.keys(evidenceCounts).map((k) => {
            const max = Math.max(...Object.values(evidenceCounts || { a: 1 }) as number[], 1);
            const height = Math.max(6, (evidenceCounts[k] / max) * 100);
            return (
              <div key={k} className="bar">
                <div className="bar-fill" style={{ height: `${height}%` }} />
                <span>{k.replace('_', ' ')}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Control Mapping</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Framework</th>
              <th>Control</th>
              <th>Signals</th>
            </tr>
          </thead>
            <tbody>
              {Object.entries(frameworks).map(([fw, data]: any) =>
              (data.controls || []).map((c: any) => (
                <tr
                  key={`${fw}-${c.id}`}
                  onClick={() => setControlFilter(`${fw}:${c.id}`)}
                  style={{ cursor: 'pointer' }}
                >
                  <td>{fw}</td>
                  <td>{c.id} · {c.name}</td>
                  <td>{(c.signals || []).join(', ')}</td>
                </tr>
              ))
              )}
            </tbody>
          </table>
        {controlFilter && (
          <div style={{ marginTop: 10 }}>
            <span className="badge">Filter: {controlFilter}</span>
            <button className="btn secondary" style={{ marginLeft: 8 }} onClick={() => setControlFilter('')}>Clear</button>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Policy Enforcement Evidence</h3>
        <div className="page-sub">Decision logs + approvals + security events. Export for audit.</div>
        <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
          <button
            className="btn"
            onClick={() => {
              const blob = new Blob([JSON.stringify(evidence || {}, null, 2)], { type: 'application/json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `shopsquire-compliance-evidence-${days}d.json`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export JSON
          </button>
        </div>
        <div style={{ marginTop: 12 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Type</th>
                <th>ID</th>
                <th>Summary</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {evidenceList.map((item: any) => (
                <tr key={`${item.type}-${item.id}`}>
                  <td>{item.type}</td>
                  <td>{item.id}</td>
                  <td>
                    {item.type === 'security' && `${item.severity || ''} ${item.path || ''}`}
                    {item.type === 'decision' && `${item.execution_status || ''} ${item.agent_name || ''}`}
                    {item.type === 'incident' && `${item.severity || ''} ${item.title || ''}`}
                  </td>
                  <td>{item.event_time || item.valid_from || item.created_at || ''}</td>
                </tr>
              ))}
              {evidenceList.length === 0 && (
                <tr>
                  <td colSpan={4}>No evidence found.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Compliance Live Feed</h3>
          <div className="page-sub">Merged security, decisions, and approvals.</div>
          <table className="table" style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th>Type</th>
                <th>Summary</th>
                <th>Tags</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {live.map((item) => (
                <tr key={`${item.type}-${item.id}`} onClick={() => setSelected(item)} style={{ cursor: 'pointer' }}>
                  <td>{item.type}</td>
                  <td>{item.summary}</td>
                  <td>
                    {item.type === 'security' && (
                      <span>
                        MITRE {Array.isArray(item.tags?.mitre) ? item.tags.mitre.join(', ') : ''}
                        {item.tags?.owasp ? ` | OWASP ${item.tags.owasp.join(', ')}` : ''}
                        {item.tags?.kev?.length ? ` | KEV ${item.tags.kev.join(', ')}` : ''}
                        {item.controls?.length ? ` | Controls ${item.controls.join(', ')}` : ''}
                      </span>
                    )}
                    {item.type === 'decision' && (
                      <span>Policy {item.tags?.policy_version} {item.tags?.approval_required ? ' | approval' : ''}</span>
                    )}
                    {item.type === 'approval' && <span>{item.tags?.capability}</span>}
                  </td>
                  <td>{item.time}</td>
                </tr>
              ))}
              {live.length === 0 && (
                <tr>
                  <td colSpan={4}>No recent events.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Selected Event</h3>
          {!selected && <div className="page-sub">Pick an event from the feed.</div>}
          {selected && (
            <>
              <div className="page-sub">Type: {selected.type}</div>
              <div className="page-sub">Summary: {selected.summary}</div>
              {selected.type === 'security' && (
                <div style={{ marginTop: 8 }}>
                  <div className="page-sub">MITRE: {(selected.tags?.mitre || []).join(', ')}</div>
                  <div className="page-sub">OWASP: {(selected.tags?.owasp || []).join(', ')}</div>
                  <div className="page-sub">STRIDE: {selected.tags?.stride ?? 'n/a'}</div>
                  <div className="page-sub">DREAD: {selected.tags?.dread ?? 'n/a'}</div>
                  <div className="page-sub">CVSS: {selected.tags?.cvss ?? 'n/a'}</div>
                  <div className="page-sub">KEV: {(selected.tags?.kev || []).join(', ') || 'n/a'}</div>
                  <div className="page-sub">Controls: {(selected.controls || []).join(', ') || 'n/a'}</div>
                </div>
              )}
              <pre className="code" style={{ marginTop: 10, maxHeight: 280, overflow: 'auto' }}>
                {JSON.stringify(selected.context, null, 2)}
              </pre>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
