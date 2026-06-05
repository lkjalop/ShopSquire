import React, { useEffect, useState } from 'react';
import { fetchMaestroBoundaries, type MaestroBoundaryEntry } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

const RISK_COLORS: Record<string, string> = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#d97706',
  low: '#16a34a',
};

const ENFORCEMENT_COLORS: Record<string, string> = {
  block: '#dc2626',
  warn: '#d97706',
  audit: '#2563eb',
};

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <span style={{
      fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 600,
      background: on ? '#fef2f2' : '#f3f4f6',
      color: on ? '#dc2626' : '#9ca3af',
      border: `1px solid ${on ? '#fca5a5' : '#e5e7eb'}`,
    }}>{label}</span>
  );
}

export function MaestroRegistry({ role }: Props) {
  const [data, setData] = useState<{
    enforcement_mode: string;
    agent_count: number;
    boundaries: Record<string, MaestroBoundaryEntry>;
    framework: string;
    control: string;
    violation_window_hours?: number | null;
    total_violations_in_window?: number | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [showViolations, setShowViolations] = useState(true);
  const [hours, setHours] = useState(24);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = (withViolations: boolean, h: number) => {
    setLoading(true);
    setError(null);
    fetchMaestroBoundaries({ include_recent_violations: withViolations, hours: h })
      .then(setData)
      .catch((e: any) => setError(e?.message || 'Failed to load boundary registry'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(showViolations, hours); }, []);

  const boundaries = data?.boundaries ?? {};
  const agents = Object.entries(boundaries).filter(([, v]) =>
    riskFilter === 'all' || v.risk_tier === riskFilter
  );

  const totalViolations = data?.total_violations_in_window ?? 0;
  const enforceMode = data?.enforcement_mode ?? 'audit';

  return (
    <div>
      <div className="page-title">MAESTRO Agentic Boundary Registry</div>
      <div className="page-sub" style={{ marginBottom: 12 }}>
        {data?.framework ?? 'CSA Agentic AI Security, Feb 2025'} — {data?.control ?? 'SC-04B'}
      </div>

      {/* Header stats row */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <div className="panel" style={{ flex: '1 1 140px', padding: '10px 14px' }}>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Enforcement Mode</div>
          <div style={{
            fontSize: 18, fontWeight: 700,
            color: ENFORCEMENT_COLORS[enforceMode] ?? '#374151',
            textTransform: 'uppercase',
          }}>{enforceMode}</div>
        </div>
        <div className="panel" style={{ flex: '1 1 120px', padding: '10px 14px' }}>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Agents Registered</div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{data?.agent_count ?? '—'}</div>
        </div>
        <div className="panel" style={{ flex: '1 1 160px', padding: '10px 14px' }}>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>
            Violations ({hours}h window)
          </div>
          <div style={{
            fontSize: 18, fontWeight: 700,
            color: totalViolations > 0 ? '#dc2626' : '#16a34a',
          }}>
            {showViolations ? totalViolations : '—'}
          </div>
        </div>
        <div className="panel" style={{ flex: '1 1 220px', padding: '10px 14px' }}>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6 }}>Violation window</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <select
              style={{ fontSize: 12 }}
              value={hours}
              onChange={(e) => {
                const h = Number(e.target.value);
                setHours(h);
                load(showViolations, h);
              }}
            >
              {[1, 6, 12, 24, 48, 72, 168].map(h => (
                <option key={h} value={h}>{h}h</option>
              ))}
            </select>
            <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
              <input
                type="checkbox"
                checked={showViolations}
                onChange={(e) => {
                  setShowViolations(e.target.checked);
                  load(e.target.checked, hours);
                }}
              />
              Live counts
            </label>
          </div>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: '#6b7280' }}>Risk tier:</span>
        {['all', 'critical', 'high', 'medium', 'low'].map(t => (
          <button
            key={t}
            className={`btn ${riskFilter === t ? '' : 'secondary'}`}
            style={{
              padding: '2px 10px', fontSize: 11,
              background: riskFilter === t ? (RISK_COLORS[t] ?? '#2563eb') : undefined,
              color: riskFilter === t ? '#fff' : undefined,
            }}
            onClick={() => setRiskFilter(t)}
          >
            {t === 'all' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
        <button
          className="btn secondary"
          style={{ marginLeft: 'auto', fontSize: 11 }}
          onClick={() => load(showViolations, hours)}
        >
          Refresh
        </button>
      </div>

      {loading && <div className="callout">Loading boundary registry…</div>}
      {error && <div className="callout" style={{ color: '#dc2626' }}>{error}</div>}

      {!loading && !error && agents.length === 0 && (
        <div className="callout">No agents match the current filter.</div>
      )}

      {!loading && !error && agents.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#f3f4f6' }}>
              <th style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '2px solid #e5e7eb' }}>Agent</th>
              <th style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '2px solid #e5e7eb' }}>Risk</th>
              <th style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '2px solid #e5e7eb' }}>Capabilities</th>
              <th style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '2px solid #e5e7eb' }}>Max $ (auto)</th>
              {showViolations && <th style={{ textAlign: 'right', padding: '6px 10px', borderBottom: '2px solid #e5e7eb' }}>Violations / Checks</th>}
              <th style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '2px solid #e5e7eb' }}>Allowed Tools</th>
            </tr>
          </thead>
          <tbody>
            {agents.map(([name, b]) => {
              const isExpanded = expanded === name;
              const hasViolations = (b.recent_violations_24h ?? 0) > 0;
              return (
                <React.Fragment key={name}>
                  <tr
                    style={{
                      borderBottom: '1px solid #f3f4f6',
                      cursor: 'pointer',
                      background: hasViolations ? '#fff7ed' : undefined,
                    }}
                    onClick={() => setExpanded(isExpanded ? null : name)}
                  >
                    <td style={{ padding: '6px 10px', fontWeight: 600, fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
                      {name}
                      <span style={{ marginLeft: 6, fontSize: 10, color: '#9ca3af' }}>{isExpanded ? '▲' : '▼'}</span>
                    </td>
                    <td style={{ padding: '6px 10px' }}>
                      <span style={{
                        background: RISK_COLORS[b.risk_tier] ?? '#6b7280',
                        color: '#fff', borderRadius: 4, padding: '1px 7px', fontSize: 10, fontWeight: 700,
                      }}>
                        {b.risk_tier?.toUpperCase() ?? '?'}
                      </span>
                    </td>
                    <td style={{ padding: '6px 10px' }}>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        <Flag on={b.can_invoke_llm} label="LLM" />
                        <Flag on={b.can_call_external_api} label="ExtAPI" />
                        <Flag on={b.can_write_db} label="WriteDB" />
                      </div>
                    </td>
                    <td style={{ padding: '6px 10px', color: '#374151' }}>
                      {b.max_autonomous_value_usd > 0 ? `$${b.max_autonomous_value_usd.toLocaleString()}` : '—'}
                    </td>
                    {showViolations && (
                      <td style={{ padding: '6px 10px', textAlign: 'right' }}>
                        <span style={{ color: hasViolations ? '#dc2626' : '#16a34a', fontWeight: hasViolations ? 700 : 400 }}>
                          {b.recent_violations_24h ?? 0}
                        </span>
                        <span style={{ color: '#9ca3af' }}> / {b.recent_checks_24h ?? 0}</span>
                      </td>
                    )}
                    <td style={{ padding: '6px 10px', color: '#374151', maxWidth: 340 }}>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {(b.allowed_tools ?? []).slice(0, 5).map((t: string) => (
                          <span key={t} style={{
                            background: '#eff6ff', color: '#1d4ed8',
                            borderRadius: 3, padding: '1px 5px', fontSize: 10, border: '1px solid #bfdbfe',
                          }}>{t}</span>
                        ))}
                        {(b.allowed_tools ?? []).length > 5 && (
                          <span style={{ fontSize: 10, color: '#9ca3af' }}>+{(b.allowed_tools ?? []).length - 5} more</span>
                        )}
                      </div>
                    </td>
                  </tr>

                  {/* Expanded detail row */}
                  {isExpanded && (
                    <tr style={{ background: '#f9fafb' }}>
                      <td colSpan={showViolations ? 6 : 5} style={{ padding: '10px 16px' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>

                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4, color: '#374151' }}>All Allowed Tools</div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                              {(b.allowed_tools ?? []).map((t: string) => (
                                <span key={t} style={{
                                  background: '#eff6ff', color: '#1d4ed8',
                                  borderRadius: 3, padding: '2px 6px', fontSize: 10, border: '1px solid #bfdbfe',
                                }}>{t}</span>
                              ))}
                              {(b.allowed_tools ?? []).length === 0 && <span style={{ color: '#9ca3af', fontSize: 11 }}>none</span>}
                            </div>
                          </div>

                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4, color: '#374151' }}>Data Scopes</div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                              {(b.allowed_data_scopes ?? []).map((s: string) => (
                                <span key={s} style={{
                                  background: '#f0fdf4', color: '#15803d',
                                  borderRadius: 3, padding: '2px 6px', fontSize: 10, border: '1px solid #bbf7d0',
                                }}>{s}</span>
                              ))}
                              {(b.allowed_data_scopes ?? []).length === 0 && <span style={{ color: '#9ca3af', fontSize: 11 }}>none</span>}
                            </div>
                          </div>

                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4, color: '#374151' }}>Trusted Peers</div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                              {(b.allowed_peers ?? []).map((p: string) => (
                                <span key={p} style={{
                                  background: '#faf5ff', color: '#7c3aed',
                                  borderRadius: 3, padding: '2px 6px', fontSize: 10, border: '1px solid #e9d5ff',
                                }}>{p}</span>
                              ))}
                              {(b.allowed_peers ?? []).length === 0 && <span style={{ color: '#9ca3af', fontSize: 11 }}>none</span>}
                            </div>
                          </div>

                          <div>
                            <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4, color: '#374151' }}>Capability Flags</div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                              {[
                                ['Invoke LLM', b.can_invoke_llm],
                                ['Call External API', b.can_call_external_api],
                                ['Write DB', b.can_write_db],
                              ].map(([label, val]) => (
                                <div key={String(label)} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                                  <span style={{ color: '#6b7280' }}>{String(label)}</span>
                                  <span style={{ fontWeight: 600, color: val ? '#dc2626' : '#16a34a' }}>{val ? 'ALLOWED' : 'DENIED'}</span>
                                </div>
                              ))}
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                                <span style={{ color: '#6b7280' }}>Max Autonomous $</span>
                                <span style={{ fontWeight: 600 }}>
                                  {b.max_autonomous_value_usd > 0 ? `$${b.max_autonomous_value_usd.toLocaleString()}` : 'none'}
                                </span>
                              </div>
                            </div>
                          </div>

                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: 16, fontSize: 11, color: '#9ca3af' }}>
        Control: {data?.control ?? 'SC-04B — Tool-call allowlist enforcement per agent'} ·
        Enforcement: <strong style={{ color: ENFORCEMENT_COLORS[enforceMode] ?? '#374151' }}>{enforceMode}</strong>
        {enforceMode === 'audit' && ' (violations are logged but agents are never blocked — set MAESTRO_ENFORCEMENT_MODE=block to harden)'}
        {enforceMode === 'block' && ' (critical/high violations raise HTTP 403)'}
      </div>
    </div>
  );
}
