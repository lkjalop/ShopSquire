import React, { useEffect, useMemo, useState } from 'react';
import { fetchLiveFeed, fetchOverview, fetchComplianceLiveFeed, fetchDemoReadiness, fetchPersonaSuccess } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

function flatten(obj: any, prefix = '', out: Record<string, string> = {}) {
  if (obj === null || obj === undefined) {
    out[prefix || 'root'] = String(obj);
    return out;
  }
  if (typeof obj !== 'object') {
    out[prefix || 'root'] = String(obj);
    return out;
  }
  const isArray = Array.isArray(obj);
  Object.keys(obj).forEach((key) => {
    const path = prefix ? (isArray ? `${prefix}[${key}]` : `${prefix}.${key}`) : key;
    flatten(obj[key], path, out);
  });
  return out;
}

function buildDiffRows(left: any, right: any) {
  const leftMap = flatten(left || {});
  const rightMap = flatten(right || {});
  const keys = Array.from(new Set([...Object.keys(leftMap), ...Object.keys(rightMap)])).sort();
  return keys.map((k) => {
    const l = leftMap[k] ?? '';
    const r = rightMap[k] ?? '';
    let kind: 'add' | 'remove' | 'change' | 'same' = 'same';
    if (!l && r) kind = 'add';
    else if (l && !r) kind = 'remove';
    else if (l !== r) kind = 'change';
    return {
      path: k,
      left: l,
      right: r,
      changed: l !== r,
      kind,
    };
  });
}

type DiffRow = { path: string; left: string; right: string; changed: boolean; kind: string };

function groupRows(rows: DiffRow[]) {
  const groups: Record<string, DiffRow[]> = {};
  rows.forEach((row) => {
    const parts = row.path.split('.');
    const group = parts.length > 1 ? `${parts[0]}.${parts[1]}` : parts[0] || 'root';
    groups[group] = groups[group] || [];
    groups[group].push(row);
  });
  return Object.entries(groups);
}

export function Overview({ role }: Props) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState({
    revenue_today: 0,
    orders_today: 0,
    autonomy_percent: 0,
    security_status: 'unknown',
    critical_events_24h: 0,
    approval_pending: 0,
    decision_series: [] as { day: string; count: number }[],
    approval_latency_p95_sec: 0,
    policy_reject_rate: 0,
    uptime_seconds: 0,
  });
  const [feed, setFeed] = useState<{ type: string; id: string; time: string; summary: string; context?: any }[]>([]);
  const [complianceFeed, setComplianceFeed] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showOnlyChanges, setShowOnlyChanges] = useState(true);
  const [demoReadiness, setDemoReadiness] = useState<any | null>(null);
  const [demoReadinessStatus, setDemoReadinessStatus] = useState<
    'loading' | 'available' | 'disabled' | 'unavailable'
  >('loading');
  const [personaSuccess, setPersonaSuccess] = useState<any | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOverview()
      .then((d) => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    fetchLiveFeed()
      .then((d) => { if (!cancelled) setFeed(d.items || []); })
      .catch(() => {});
    if (role === 'owner') {
      fetchComplianceLiveFeed(10)
        .then((d) => { if (!cancelled) setComplianceFeed(d.items || []); })
        .catch(() => {});
    }
    setDemoReadinessStatus('loading');
    fetchDemoReadiness(24)
      .then((d) => {
        if (!cancelled) {
          setDemoReadiness(d);
          setDemoReadinessStatus('available');
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          setDemoReadiness(null);
          setDemoReadinessStatus(err?.status === 404 ? 'disabled' : 'unavailable');
        }
      });
    fetchPersonaSuccess(7).then((d) => { if (!cancelled) setPersonaSuccess(d); }).catch(() => {});
    return () => { cancelled = true; };
  }, [role]);

  const series = useMemo(() => {
    if (!data.decision_series.length) return [];
    return data.decision_series;
  }, [data.decision_series]);
  const readinessFallback = demoReadinessStatus === 'disabled'
    ? 'Disabled'
    : demoReadinessStatus === 'loading'
      ? 'Loading'
      : 'Unavailable';
  const readinessValue = (value: unknown, format?: (n: number) => string) => {
    if (demoReadinessStatus !== 'available' || typeof value !== 'number') return readinessFallback;
    return format ? format(value) : value;
  };
  return (
    <div className="stagger">
      <div className="grid-4">
        <div className="card">
          <h3>Revenue Today</h3>
          <div className="metric">${data.revenue_today.toLocaleString()}</div>
          <div className="badge" data-testid="revenue-comparison-status">
            {data.revenue_today === 0 ? 'No revenue recorded today' : 'WoW comparison unavailable'}
          </div>
        </div>
        <div className="card">
          <h3>Orders Today</h3>
          <div className="metric">{data.orders_today}</div>
          <div className="badge" data-testid="order-approval-status">
            {data.orders_today === 0 ? 'No orders recorded today' : 'Approval rate unavailable'}
          </div>
        </div>
        <div className="card">
          <h3>AI Autonomy</h3>
          <div className="metric">{data.autonomy_percent}%</div>
          <div className="badge">Guardrails active</div>
        </div>
        <div className="card">
          <h3>Security Status</h3>
          <div className="metric">{data.security_status}</div>
          <div className="badge">{data.critical_events_24h} critical</div>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Decision Throughput</h3>
          <div className="chart" aria-hidden="true">
            {series.length === 0 && <div className="page-sub" style={{ padding: 12 }}>No data</div>}
            {series.length > 0 && (
              <div className="bar-chart">
                {series.map((p) => (
                  <div key={p.day} className="bar">
                    <div className="bar-fill" style={{ height: `${Math.max(6, (p.count / Math.max(...series.map(s => s.count), 1)) * 100)}%` }} />
                    <span>{new Date(p.day).toLocaleDateString(undefined, { weekday: 'short' })}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="list">
            <div className="list-item">
              <div>Approval latency</div>
              <strong>{data.approval_latency_p95_sec}s p95</strong>
            </div>
            <div className="list-item">
              <div>Policy rejects</div>
              <strong>{Math.round(data.policy_reject_rate * 100)}%</strong>
            </div>
            <div className="list-item">
              <div>Pending approvals</div>
              <strong>{data.approval_pending}</strong>
            </div>
            <div className="list-item">
              <div>Uptime</div>
              <strong>{Math.round(data.uptime_seconds / 60)} min</strong>
            </div>
          </div>
        </div>

        <div className="card">
          <h3>Live Feed</h3>
          <div className="list">
            {feed.length === 0 && <div className="page-sub">No recent events.</div>}
            {feed.map((item) => (
              <div key={`${item.type}-${item.id}`} className={`list-item ${selectedId === item.id ? 'active' : ''}`}>
                <div>
                  <div>{item.summary}</div>
                  {item.context && (
                    <div className="page-sub">
                      {item.type === 'decision' && item.context.query && `Query: ${item.context.query}`}
                      {item.type === 'security' && (
                        <>
                          {item.context.path && `Path: ${item.context.path} `}
                          {item.context.score !== undefined && `Score: ${item.context.score} `}
                          {item.context.mitre && `MITRE: ${item.context.mitre}`}
                        </>
                      )}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span className="badge">{new Date(item.time).toLocaleTimeString()}</span>
                  <button className="btn secondary" onClick={() => setSelectedId(selectedId === item.id ? null : item.id)}>
                    {selectedId === item.id ? 'Hide' : 'View'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Security Posture</h3>
          {demoReadinessStatus !== 'available' && (
            <div className="page-sub" data-testid="demo-readiness-status">
              Demo-readiness evidence: {readinessFallback.toLowerCase()}. Values below are not measured zeros.
            </div>
          )}
          <div className="list">
            <div className="list-item"><div>Blocked attacks</div><strong>{readinessValue(demoReadiness?.security_posture?.blocked_attacks)}</strong></div>
            <div className="list-item"><div>Escalations</div><strong>{readinessValue(demoReadiness?.security_posture?.escalations)}</strong></div>
            <div className="list-item"><div>Supplier quarantines</div><strong>{readinessValue(demoReadiness?.security_posture?.supplier_quarantines)}</strong></div>
            <div className="list-item"><div>API abuse blocked</div><strong>{readinessValue(demoReadiness?.security_posture?.api_abuse_blocked)}</strong></div>
          </div>
        </div>
        <div className="card">
          <h3>Model Quality</h3>
          <div className="list">
            <div className="list-item"><div>Upsell CTR</div><strong>{readinessValue(demoReadiness?.model_quality?.ctr, (n) => `${(n * 100).toFixed(1)}%`)}</strong></div>
            <div className="list-item"><div>Add-to-cart uplift</div><strong>{readinessValue(demoReadiness?.model_quality?.add_to_cart_rate, (n) => `${(n * 100).toFixed(1)}%`)}</strong></div>
            <div className="list-item"><div>Low-confidence fallback rate</div><strong>{readinessValue(demoReadiness?.model_quality?.low_confidence_fallback_rate, (n) => `${(n * 100).toFixed(1)}%`)}</strong></div>
            <div className="list-item"><div>Fallback count</div><strong>{readinessValue(demoReadiness?.model_quality?.low_confidence_count)}</strong></div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Persona Success Dashboard</h3>
        <div className="page-sub">Resolution turns, reformulation rate, and image reupload rate by inferred persona.</div>
        <div className="list" style={{ marginTop: 8 }}>
          {(!personaSuccess?.personas || personaSuccess.personas.length === 0) && (
            <div className="page-sub">No persona metrics available for selected window.</div>
          )}
          {(personaSuccess?.personas || []).slice(0, 6).map((row: any) => (
            <div key={String(row.persona)} className="list-item">
              <div>
                <strong>{String(row.persona || 'unknown')}</strong>
                <div className="page-sub">Traces: {Number(row.traces || 0)}</div>
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <span className="badge">Resolution turns: {Number(row.resolution_turns_avg || 0).toFixed(2)}</span>
                <span className="badge">Reformulation: {(Number(row.reformulation_rate || 0) * 100).toFixed(1)}%</span>
                <span className="badge">Reupload: {(Number(row.reupload_rate || 0) * 100).toFixed(1)}%</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {role === 'owner' && (
        <div className="card" style={{ marginTop: 16 }}>
          <h3>Compliance Live Feed</h3>
          <div className="page-sub">Owner-only merged security/decisions/approvals with control mappings.</div>
          <div className="list" style={{ marginTop: 8 }}>
            {complianceFeed.length === 0 && <div className="page-sub">No recent compliance events.</div>}
            {complianceFeed.map((item) => (
              <div key={`${item.type}-${item.id}`} className="list-item">
                <div>
                  <div>{item.summary}</div>
                  <div className="page-sub">
                    {item.type === 'security' && `MITRE: ${(item.tags?.mitre || []).join(', ')} | Controls: ${(item.controls || []).join(', ')}`}
                    {item.type === 'decision' && `Policy: ${item.tags?.policy_version} | Controls: ${(item.controls || []).join(', ')}`}
                    {item.type === 'approval' && `Capability: ${item.tags?.capability} | Controls: ${(item.controls || []).join(', ')}`}
                  </div>
                </div>
                <span className="badge">{new Date(item.time).toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {selectedId && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Event Detail</h3>
          {feed.filter(i => i.id === selectedId).map(item => (
            <div key={item.id}>
              <div className="list">
                <div className="list-item"><div>Type</div><strong>{item.type}</strong></div>
                <div className="list-item"><div>Time</div><strong>{new Date(item.time).toLocaleString()}</strong></div>
                {item.type === 'decision' && (
                  <>
                    <div className="list-item"><div>Policy Version</div><strong>{item.context?.policy_version || 'n/a'}</strong></div>
                    <div className="list-item"><div>Approval Required</div><strong>{String(item.context?.approval_required)}</strong></div>
                  </>
                )}
                {item.type === 'security' && (
                  <>
                    <div className="list-item"><div>Score</div><strong>{item.context?.score}</strong></div>
                    <div className="list-item"><div>MITRE</div><strong>{item.context?.mitre || 'n/a'}</strong></div>
                  </>
                )}
              </div>
              <div style={{ marginTop: 12 }}>
                <strong>Context</strong>
                {item.type === 'decision' && (
                  <div className="split">
                    <div>
                      <div className="page-sub">Input</div>
                      <pre className="panel">{JSON.stringify(item.context?.input_data || {}, null, 2)}</pre>
                    </div>
                    <div>
                      <div className="page-sub">Proposed Action</div>
                      <pre className="panel">{JSON.stringify(item.context?.proposed_action || {}, null, 2)}</pre>
                    </div>
                  </div>
                )}
                {item.type === 'security' && (
                  <div className="split">
                    <div>
                      <div className="page-sub">Raw Payload</div>
                      <pre className="panel">{JSON.stringify(item.context?.raw || {}, null, 2)}</pre>
                    </div>
                    <div>
                      <div className="page-sub">Analysis</div>
                      <pre className="panel">{JSON.stringify(item.context?.analysis || {}, null, 2)}</pre>
                    </div>
                  </div>
                )}
                {!item.type && <pre className="panel">{JSON.stringify(item.context || {}, null, 2)}</pre>}
                {(item.type === 'decision' || item.type === 'security') && (
                  <div style={{ marginTop: 12 }}>
                    <div className="page-sub" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>Inline diff (delta view)</span>
                      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
                        <input
                          type="checkbox"
                          checked={showOnlyChanges}
                          onChange={(e) => setShowOnlyChanges(e.target.checked)}
                        />
                        Only changes
                      </label>
                    </div>
                    <table className="diff-table">
                      <thead>
                        <tr>
                          <th>Field</th>
                          <th>Left</th>
                          <th>Right</th>
                        </tr>
                      </thead>
                      <tbody>
                        {groupRows(buildDiffRows(
                          item.type === 'decision' ? item.context?.input_data : item.context?.raw,
                          item.type === 'decision' ? item.context?.proposed_action : item.context?.analysis
                        ))
                          .map(([group, rows]) => {
                            const filtered = rows.filter((row) => (showOnlyChanges ? row.changed : true));
                            if (!filtered.length) return null;
                            return (
                              <React.Fragment key={group}>
                                <tr className="diff-group">
                                  <td colSpan={3}>{group}</td>
                                </tr>
                                {filtered.map((row) => (
                                  <tr key={row.path} className={row.changed ? `diff-changed diff-${row.kind}` : ''}>
                                    <td>{row.path}</td>
                                    <td>{row.left}</td>
                                    <td>{row.right}</td>
                                  </tr>
                                ))}
                              </React.Fragment>
                            );
                          })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 16 }} className="panel">
        <strong>Role visibility</strong>
        <div className="page-sub">
          {role === 'merchant' && 'Merchant view: operational metrics, approvals, and security posture.'}
          {role === 'owner' && 'Owner view: adds billing, governance exports, and tenant controls.'}
          {role === 'developer' && 'Developer view: adds API keys, webhooks, and sandbox logs.'}
        </div>
        {loading && <div className="page-sub">Refreshing metrics...</div>}
      </div>
    </div>
  );
}
