import React, { useEffect, useState, useCallback } from 'react';
import { apiUrl, safeJson } from '../lib/api';
import { apiFetch } from '../lib/csrf';
import { getOwnerApiKey } from '../lib/browserSession';

type TabId = 'overview' | 'nqe' | 'recommendations' | 'fraud' | 'supply_chain' | 'intelligence' | 'persona' | 'security_scorecard' | 'integration_health';

interface MetricCard {
  label: string;
  value: string | number;
  trend?: 'up' | 'down' | 'flat';
  detail?: string;
}

interface CitationStats {
  agent_name: string;
  total_claims: number;
  verified_claims: number;
  correct_claims: number;
  accuracy_rate: number;
  avg_trust_score: number;
  pending_claims: number;
}

interface UserProfileData {
  user_id: string;
  found: boolean;
  preferred_brands?: string[];
  avoided_brands?: string[];
  budget_tier?: string;
  typical_use_cases?: string[];
  last_session_summary?: string;
  updated_at?: number;
}

interface ObservationSummary {
  compressed_at?: number;
  total_events?: number;
  event_types?: Record<string, any>;
}

const TAB_CONFIG: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Executive Overview' },
  { id: 'nqe', label: 'NQE Analytics' },
  { id: 'recommendations', label: 'Recommendation Performance' },
  { id: 'fraud', label: 'Fraud / Security' },
  { id: 'supply_chain', label: 'Supply Chain Health' },
  { id: 'intelligence', label: 'Agent Intelligence' },
  { id: 'persona', label: 'Persona Intelligence' },
  { id: 'security_scorecard', label: '🛡 Security Scorecard' },
  { id: 'integration_health', label: '⚡ Integration Health' },
];

function ownerHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = getOwnerApiKey();
  return {
    ...(key ? { 'x-api-key': key } : {}),
    ...extra,
  };
}

async function adminGet(path: string): Promise<any | null> {
  try {
    const r = await fetch(apiUrl(path), {
      credentials: 'include',
      headers: ownerHeaders(),
    });
    return await safeJson(r);
  } catch {
    return null;
  }
}

function MetricCardComponent({ card }: { card: MetricCard }) {
  const trendIcon = card.trend === 'up' ? '▲' : card.trend === 'down' ? '▼' : '—';
  const trendColor = card.trend === 'up' ? '#22c55e' : card.trend === 'down' ? '#ef4444' : '#94a3b8';
  return (
    <div style={{
      border: '1px solid rgba(148,163,184,0.18)',
      borderRadius: 12,
      padding: '14px 16px',
      background: 'rgba(15,23,42,0.45)',
      minWidth: 180,
      flex: '1 1 180px',
    }}>
      <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>{card.label}</div>
      <div style={{ fontSize: 24, fontWeight: 700 }}>{card.value}</div>
      {card.trend && (
        <div style={{ fontSize: 11, color: trendColor, marginTop: 2 }}>
          {trendIcon} {card.detail || ''}
        </div>
      )}
    </div>
  );
}

function OverviewTab() {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const j = await adminGet('/status/summary');
        setStatus(j);
      } catch { setStatus(null); }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div style={{ padding: 16 }}>Loading...</div>;

  const cards: MetricCard[] = [
    { label: 'Email Warnings', value: status?.email_xdr?.warnings ?? 0, trend: 'flat' },
    { label: 'Outbound Anomalies', value: status?.outbound_anomalies ?? 0, trend: 'flat' },
    { label: 'Active Sessions', value: status?.active_sessions ?? '-', trend: 'flat' },
    { label: 'Decision Traces (24h)', value: status?.decision_traces_24h ?? '-', trend: 'up', detail: 'vs prior period' },
  ];

  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Executive Overview</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        {cards.map((c, i) => <MetricCardComponent key={i} card={c} />)}
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12,
        background: 'rgba(15,23,42,0.45)',
        padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Quick Links</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {[
            ['Query Clusters', '/api/v1/analytics/query_clusters/latest'],
            ['Metrics', '/metrics'],
            ['Health', '/healthz'],
          ].map(([label, url]) => (
            <a key={url} href={url} target="_blank" rel="noreferrer" style={{
              padding: '6px 10px', borderRadius: 10, border: '1px solid rgba(148,163,184,0.25)',
              color: '#e5e7eb', textDecoration: 'none', fontSize: 12,
            }}>{label}</a>
          ))}
        </div>
      </div>
    </div>
  );
}

function NQEAnalyticsTab() {
  const [clusters, setClusters] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const j = await adminGet('/api/v1/analytics/query_clusters/latest?limit=15');
        setClusters(j?.items || []);
      } catch { setClusters([]); }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div style={{ padding: 16 }}>Loading NQE analytics...</div>;

  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>NQE Analytics</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <MetricCardComponent card={{ label: 'Query Clusters', value: clusters.length }} />
        <MetricCardComponent card={{ label: 'Total Queries', value: clusters.reduce((a, c) => a + (c.size || 0), 0) }} />
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12,
        background: 'rgba(15,23,42,0.45)',
        padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Top Question Clusters</div>
        {clusters.length === 0 ? (
          <div style={{ color: '#94a3b8', fontSize: 13 }}>No cluster data yet.</div>
        ) : (
          clusters.map((c, i) => (
            <div key={i} style={{
              padding: '8px 10px', borderBottom: '1px solid rgba(148,163,184,0.1)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{c.label || 'Unnamed cluster'}</div>
                <div style={{ fontSize: 11, color: '#94a3b8' }}>
                  {(c.top_k_exemplars || []).slice(0, 2).join(' | ')}
                </div>
              </div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{c.size || 0}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function RecommendationTab() {
  const [snapshot, setSnapshot] = useState<any>(null);

  useEffect(() => {
    const refresh = () => {
      try {
        const raw = localStorage.getItem('shopsquire_operator_metrics');
        setSnapshot(raw ? JSON.parse(raw) : null);
      } catch {
        setSnapshot(null);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    window.addEventListener('storage', refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('storage', refresh);
    };
  }, []);

  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Recommendation Performance</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <MetricCardComponent card={{ label: 'Latest Route', value: snapshot?.routeTotalMs != null ? `${Math.round(Number(snapshot.routeTotalMs))} ms` : 'No data', trend: 'flat', detail: 'latest route latency' }} />
        <MetricCardComponent card={{ label: 'Catalog Profile', value: snapshot?.catalogProfileMs != null ? `${Math.round(Number(snapshot.catalogProfileMs))} ms` : 'No data', trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Fallback Used', value: snapshot?.recommendationFallbackUsed ? 'Yes' : 'No', trend: snapshot?.recommendationFallbackUsed ? 'down' : 'flat', detail: 'latest session' }} />
        <MetricCardComponent card={{ label: 'Timeout Seen', value: snapshot?.recommendationTimeout ? 'Yes' : 'No', trend: snapshot?.recommendationTimeout ? 'down' : 'flat', detail: 'latest session' }} />
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Latest Recommendation Telemetry</div>
        <div style={{ color: '#94a3b8', fontSize: 13, display: 'grid', gap: 6 }}>
          <div>QR decode observed: {snapshot?.qrDecodeSuccess == null ? 'No data' : snapshot.qrDecodeSuccess ? 'Yes' : 'No'}</div>
          <div>Linked artifact fetch observed: {snapshot?.linkedArtifactFetch == null ? 'No data' : snapshot.linkedArtifactFetch ? 'Yes' : 'No'}</div>
          <div>Security review required: {snapshot?.securityReviewRequired == null ? 'No data' : snapshot.securityReviewRequired ? 'Yes' : 'No'}</div>
          <div>Source: {snapshot?.source || 'unknown'}{snapshot?.recordedAt ? ` • ${snapshot.recordedAt}` : ''}</div>
        </div>
      </div>
    </div>
  );
}

function FraudSecurityTab() {
  const [citationStats, setCitationStats] = useState<CitationStats | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const j = await adminGet('/api/v1/merchant/intelligence/citation_memory/stats');
        setCitationStats(j);
      } catch { setCitationStats(null); }
    })();
  }, []);

  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Fraud / Security</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <MetricCardComponent card={{ label: 'Total Claims', value: citationStats?.total_claims ?? '-' }} />
        <MetricCardComponent card={{ label: 'Verified', value: citationStats?.verified_claims ?? '-' }} />
        <MetricCardComponent card={{
          label: 'Accuracy Rate',
          value: citationStats ? `${(citationStats.accuracy_rate * 100).toFixed(1)}%` : '-',
          trend: (citationStats?.accuracy_rate ?? 0) > 0.8 ? 'up' : 'down',
        }} />
        <MetricCardComponent card={{
          label: 'Avg Trust Score',
          value: citationStats?.avg_trust_score?.toFixed(3) ?? '-',
        }} />
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Agent Trust Scores</div>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          Pending claims: {citationStats?.pending_claims ?? '-'}
        </div>
      </div>
    </div>
  );
}

function SupplyChainTab() {
  const [snapshot, setSnapshot] = useState<any>(null);

  useEffect(() => {
    const refresh = () => {
      try {
        const raw = localStorage.getItem('shopsquire_operator_metrics');
        setSnapshot(raw ? JSON.parse(raw) : null);
      } catch {
        setSnapshot(null);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    window.addEventListener('storage', refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('storage', refresh);
    };
  }, []);

  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Supply Chain Health</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <MetricCardComponent card={{ label: 'QR Decode Success', value: snapshot?.qrDecodeSuccess == null ? 'No data' : snapshot.qrDecodeSuccess ? 'Yes' : 'No', trend: snapshot?.qrDecodeSuccess ? 'up' : 'flat' }} />
        <MetricCardComponent card={{ label: 'Linked Fetch Seen', value: snapshot?.linkedArtifactFetch == null ? 'No data' : snapshot.linkedArtifactFetch ? 'Yes' : 'No', trend: snapshot?.linkedArtifactFetch ? 'up' : 'flat' }} />
        <MetricCardComponent card={{ label: 'Security Review', value: snapshot?.securityReviewRequired == null ? 'No data' : snapshot.securityReviewRequired ? 'Yes' : 'No', trend: snapshot?.securityReviewRequired ? 'down' : 'flat' }} />
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Live Security Telemetry</div>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          This tab now reflects live storefront operator metrics instead of placeholder cards.
          Use <a href="/api/v1/admin/supply_chain/anomalies/default" target="_blank" style={{ color: '#60a5fa' }}>
            the anomaly API
          </a> and <a href="/metrics" target="_blank" style={{ color: '#60a5fa' }}>
            runtime metrics
          </a> for backend detail.
        </div>
      </div>
    </div>
  );
}

function PersonaIntelligenceTab() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);

  useEffect(() => {
    setLoading(true);
    adminGet(`/api/v1/admin/bi/persona-success?days=${days}`)
      .then(j => setData(j))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [days]);

  const cardStyle: React.CSSProperties = {
    border: '1px solid rgba(148,163,184,0.18)',
    borderRadius: 12,
    background: 'rgba(15,23,42,0.45)',
    padding: 14,
    marginBottom: 12,
  };

  if (loading) return <div style={{ padding: 16 }}>Loading persona intelligence...</div>;

  const personas: any[] = data?.personas ?? [];
  const totals = data?.totals ?? {};
  const windowInfo = data?.window ?? {};

  return (
    <div>
      <h3 style={{ margin: '0 0 8px', fontSize: 16, fontWeight: 600 }}>Persona Intelligence</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, fontSize: 13, color: '#94a3b8' }}>
        <span>Window:</span>
        {[7, 14, 30].map(d => (
          <button key={d} onClick={() => setDays(d)} style={{
            padding: '4px 10px', borderRadius: 8, cursor: 'pointer', fontSize: 12,
            background: days === d ? 'rgba(249,115,22,0.18)' : 'rgba(15,23,42,0.85)',
            color: '#e5e7eb',
            border: `1px solid ${days === d ? 'rgba(249,115,22,0.65)' : 'rgba(148,163,184,0.2)'}`,
          }}>{d}d</button>
        ))}
        {windowInfo.start && <span style={{ fontSize: 11 }}>{windowInfo.start} → {windowInfo.end}</span>}
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <MetricCardComponent card={{ label: 'Decision Traces', value: totals.traces ?? 0, trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Reformulated Queries', value: totals.reformulated ?? 0, trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Reupload Required', value: totals.reupload_required ?? 0, trend: 'flat' }} />
      </div>

      <div style={cardStyle}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>Shopper Persona Distribution</div>
        {personas.length === 0 ? (
          <div style={{ color: '#94a3b8', fontSize: 13 }}>
            No persona data yet — persona signals are captured once shoppers submit queries with intent cues.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: '#94a3b8', borderBottom: '1px solid rgba(148,163,184,0.2)' }}>
                <th style={{ textAlign: 'left', padding: '4px 8px' }}>Persona</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Sessions</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Avg Confidence</th>
                <th style={{ textAlign: 'right', padding: '4px 8px' }}>Reformulated</th>
                <th style={{ padding: '4px 8px' }}>Share</th>
              </tr>
            </thead>
            <tbody>
              {personas.map((p: any, i: number) => {
                const share = totals.traces > 0 ? Math.round((p.count / totals.traces) * 100) : 0;
                const barColor = ['#7C3AED', '#0891b2', '#059669', '#d97706', '#dc2626'][i % 5];
                return (
                  <tr key={p.persona || i} style={{ borderBottom: '1px solid rgba(148,163,184,0.1)' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 600 }}>{p.persona || 'unknown'}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.count ?? 0}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.avg_confidence != null ? `${Math.round(p.avg_confidence * 100)}%` : '—'}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.reformulated ?? 0}</td>
                    <td style={{ padding: '6px 8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ flex: 1, background: 'rgba(148,163,184,0.15)', borderRadius: 4, height: 8 }}>
                          <div style={{ width: `${share}%`, background: barColor, borderRadius: 4, height: 8, transition: 'width 0.4s' }} />
                        </div>
                        <span style={{ minWidth: 28, textAlign: 'right', fontSize: 11 }}>{share}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ ...cardStyle, fontSize: 13, color: '#94a3b8' }}>
        <div style={{ fontWeight: 600, color: '#e5e7eb', marginBottom: 6 }}>Trace Navigation</div>
        Open any recommendation trace and switch to the <strong style={{ color: '#7C3AED' }}>Intent</strong> tab to see the full shopper
        intent profile (persona, urgency, bundle receptivity, priority factors) captured bitemporally for that decision.
      </div>
    </div>
  );
}

function IntelligenceTab() {
  const [profileId, setProfileId] = useState('');
  const [profile, setProfile] = useState<UserProfileData | null>(null);
  const [behavioral, setBehavioral] = useState<any>(null);
  const [obsSessionId, setObsSessionId] = useState('');
  const [obsSummary, setObsSummary] = useState<ObservationSummary | null>(null);

  const loadProfile = useCallback(async () => {
    if (!profileId.trim()) return;
    try {
      const j = await adminGet(`/api/v1/merchant/intelligence/user_profiles/${encodeURIComponent(profileId)}`);
      setProfile(j);
      const j2 = await adminGet(`/api/v1/merchant/intelligence/user_profiles/${encodeURIComponent(profileId)}/behavioral_model`);
      setBehavioral(j2);
    } catch { setProfile(null); setBehavioral(null); }
  }, [profileId]);

  const loadObservation = useCallback(async () => {
    if (!obsSessionId.trim()) return;
    try {
      const j = await adminGet(`/api/v1/merchant/intelligence/observation_summary/${encodeURIComponent(obsSessionId)}`);
      setObsSummary(j?.summary || null);
    } catch { setObsSummary(null); }
  }, [obsSessionId]);

  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Agent Intelligence Metrics</h3>

      {/* User Profile Lookup */}
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14, marginBottom: 12,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Returning Customer Profile</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <input
            value={profileId} onChange={(e) => setProfileId(e.target.value)}
            placeholder="User ID" onKeyDown={(e) => e.key === 'Enter' && loadProfile()}
            style={{
              padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)',
              background: '#0b1220', color: '#e5e7eb', minWidth: 200,
            }}
          />
          <button onClick={loadProfile} style={{
            padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)',
            background: '#111827', color: '#e5e7eb', cursor: 'pointer',
          }}>Load</button>
        </div>
        {profile && profile.found ? (
          <div style={{ fontSize: 12 }}>
            <div><strong>Preferred Brands:</strong> {(profile.preferred_brands || []).join(', ') || 'none'}</div>
            <div><strong>Avoided Brands:</strong> {(profile.avoided_brands || []).join(', ') || 'none'}</div>
            <div><strong>Budget Tier:</strong> {profile.budget_tier || 'unknown'}</div>
            <div><strong>Typical Use Cases:</strong> {(profile.typical_use_cases || []).join(', ') || 'none'}</div>
            <div><strong>Last Session:</strong> {profile.last_session_summary || 'n/a'}</div>
            {behavioral && (
              <>
                <div style={{ marginTop: 8, fontWeight: 600 }}>Behavioral Model</div>
                <div><strong>Decision Style:</strong> {behavioral.decision_style || '-'}</div>
                <div><strong>Comparison Style:</strong> {behavioral.comparison_style || '-'}</div>
                <div><strong>Avg Turns:</strong> {behavioral.avg_turns_per_session ?? '-'}</div>
                <div><strong>Avg Products Compared:</strong> {behavioral.avg_products_compared ?? '-'}</div>
              </>
            )}
          </div>
        ) : profile ? (
          <div style={{ color: '#94a3b8', fontSize: 12 }}>No profile found for this user.</div>
        ) : null}
      </div>

      {/* Observation Summary Lookup */}
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Observation Summary (Session)</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <input
            value={obsSessionId} onChange={(e) => setObsSessionId(e.target.value)}
            placeholder="Session ID" onKeyDown={(e) => e.key === 'Enter' && loadObservation()}
            style={{
              padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)',
              background: '#0b1220', color: '#e5e7eb', minWidth: 200,
            }}
          />
          <button onClick={loadObservation} style={{
            padding: '6px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,0.25)',
            background: '#111827', color: '#e5e7eb', cursor: 'pointer',
          }}>Load</button>
        </div>
        {obsSummary ? (
          <div style={{ fontSize: 12 }}>
            <div><strong>Total Events:</strong> {obsSummary.total_events ?? 0}</div>
            {obsSummary.event_types && Object.entries(obsSummary.event_types).map(([type, data]) => (
              <div key={type} style={{ marginTop: 4 }}>
                <strong>{type}:</strong> {(data as any)?.count ?? 0} events
                {(data as any)?.models_used && (
                  <span style={{ color: '#94a3b8' }}> — models: {Object.keys((data as any).models_used).join(', ')}</span>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

const GRADE_COLORS: Record<string, string> = {
  A: '#22c55e', B: '#86efac', C: '#facc15', D: '#f97316', F: '#ef4444',
};

function SecurityScorecardTab() {
  const [scorecard, setScorecard] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [running, setRunning] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);

  const load = async (d: number) => {
    setLoading(true);
    try {
      setScorecard(await adminGet(`/api/v1/security/scan/scorecard?days=${d}`));
    } catch { setScorecard(null); }
    setLoading(false);
  };

  useEffect(() => { load(days); }, [days]);

  const triggerScan = async () => {
    setRunning(true);
    setScanResult(null);
    try {
      const data = await apiFetch<any>('/api/v1/security/scan/full', {
        method: 'POST',
        headers: ownerHeaders(),
      });
      setScanResult(data);
    } catch (e: any) { setScanResult({ error: String(e) }); }
    setRunning(false);
    load(days);
  };

  const grade = scorecard?.posture_grade ?? '—';
  const gradeColor = GRADE_COLORS[grade] ?? '#94a3b8';

  if (loading) return <div style={{ padding: 16 }}>Loading scorecard...</div>;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Security Posture Scorecard</h3>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
          style={{ background: '#111827', color: '#e5e7eb', border: '1px solid rgba(148,163,184,0.25)', borderRadius: 8, padding: '4px 8px', fontSize: 13 }}>
          {[7, 14, 30, 90].map(d => <option key={d} value={d}>Last {d} days</option>)}
        </select>
        <button onClick={triggerScan} disabled={running}
          style={{ padding: '6px 12px', borderRadius: 8, border: 'none', background: running ? '#374151' : '#dc2626', color: '#fff', cursor: running ? 'not-allowed' : 'pointer', fontSize: 13 }}>
          {running ? 'Scanning...' : 'Run Scan Now'}
        </button>
      </div>

      {/* Grade badge */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 12, padding: '14px 20px', background: 'rgba(15,23,42,0.45)', minWidth: 120, textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Posture Grade</div>
          <div style={{ fontSize: 40, fontWeight: 800, color: gradeColor }}>{grade}</div>
        </div>
        <MetricCardComponent card={{ label: 'Total Incidents', value: scorecard?.incident_total ?? 0 }} />
        <MetricCardComponent card={{ label: 'Open Critical/High', value: (scorecard?.open_critical_high ?? []).length }} />
        <MetricCardComponent card={{ label: 'Recent Scans', value: (scorecard?.recent_scans ?? []).length }} />
        <MetricCardComponent card={{
          label: 'Scanner Status',
          value: scorecard?.trivy_available ? 'Trivy ✓' : scorecard?.scanner_available ? 'Available' : 'No scanner',
        }} />
      </div>

      {/* Summary */}
      {scorecard?.posture_summary && (
        <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 10, padding: '10px 14px', background: 'rgba(15,23,42,0.45)', marginBottom: 12, fontSize: 13, color: '#cbd5e1' }}>
          {scorecard.posture_summary}
        </div>
      )}

      {/* Incident breakdown */}
      {scorecard?.incident_counts && Object.keys(scorecard.incident_counts).length > 0 && (
        <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 12, padding: 14, background: 'rgba(15,23,42,0.45)', marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Incident Severity Breakdown</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(scorecard.incident_counts as Record<string, number>).map(([sev, cnt]) => (
              <div key={sev} style={{ padding: '6px 12px', borderRadius: 8, background: 'rgba(30,41,59,0.7)', border: '1px solid rgba(148,163,184,0.2)', fontSize: 13 }}>
                <span style={{ color: GRADE_COLORS[sev === 'critical' ? 'F' : sev === 'high' ? 'D' : sev === 'medium' ? 'C' : 'A'] || '#94a3b8', fontWeight: 600, textTransform: 'capitalize' }}>{sev}</span>
                <span style={{ color: '#e5e7eb', marginLeft: 6 }}>{cnt}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Open critical/high */}
      {(scorecard?.open_critical_high ?? []).length > 0 && (
        <div style={{ border: '1px solid rgba(239,68,68,0.3)', borderRadius: 12, padding: 14, background: 'rgba(15,23,42,0.45)', marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#fca5a5' }}>Open Critical / High Incidents</div>
          {scorecard.open_critical_high.map((inc: any) => (
            <div key={inc.id} style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid rgba(148,163,184,0.1)', fontSize: 12 }}>
              <span style={{ color: inc.severity === 'critical' ? '#ef4444' : '#f97316', fontWeight: 700, minWidth: 56, textTransform: 'uppercase', fontSize: 10 }}>{inc.severity}</span>
              <span style={{ color: '#e5e7eb', flex: 1 }}>{inc.title}</span>
              <span style={{ color: '#64748b', minWidth: 100, textAlign: 'right' }}>{inc.created_at?.slice(0, 10)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Recent scans */}
      {(scorecard?.recent_scans ?? []).length > 0 && (
        <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 12, padding: 14, background: 'rgba(15,23,42,0.45)', marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Recent Scan Scorecards</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: '#94a3b8', textAlign: 'left' }}>
                <th style={{ padding: '4px 8px' }}>Target</th>
                <th style={{ padding: '4px 8px' }}>Risk Score</th>
                <th style={{ padding: '4px 8px' }}>Total</th>
                <th style={{ padding: '4px 8px' }}>Critical</th>
                <th style={{ padding: '4px 8px' }}>High</th>
                <th style={{ padding: '4px 8px' }}>Date</th>
              </tr>
            </thead>
            <tbody>
              {scorecard.recent_scans.map((s: any, i: number) => (
                <tr key={i} style={{ borderTop: '1px solid rgba(148,163,184,0.1)', color: '#e5e7eb' }}>
                  <td style={{ padding: '5px 8px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.target || '—'}</td>
                  <td style={{ padding: '5px 8px', color: s.risk_score > 7 ? '#ef4444' : s.risk_score > 4 ? '#f97316' : '#22c55e' }}>{s.risk_score?.toFixed(1)}</td>
                  <td style={{ padding: '5px 8px' }}>{s.total_findings}</td>
                  <td style={{ padding: '5px 8px', color: s.critical > 0 ? '#ef4444' : '#e5e7eb' }}>{s.critical}</td>
                  <td style={{ padding: '5px 8px', color: s.high > 0 ? '#f97316' : '#e5e7eb' }}>{s.high}</td>
                  <td style={{ padding: '5px 8px', color: '#64748b' }}>{s.created_at?.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Live scan result */}
      {scanResult && (
        <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 12, padding: 14, background: 'rgba(15,23,42,0.45)', marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Last Scan Output</div>
          {scanResult.error
            ? <div style={{ color: '#ef4444', fontSize: 12 }}>{scanResult.error}</div>
            : <div style={{ fontSize: 12, color: '#94a3b8' }}>
                {scanResult.vuln_scan_enabled === false
                  ? 'Scanning is disabled (VULN_SCAN_ENABLED=0). Enable it and try again.'
                  : `Findings: ${scanResult.total_findings ?? 0} · Critical: ${scanResult.critical_count ?? 0} · DREAD avg: ${scanResult.dread?.avg?.toFixed(1) ?? '—'}`
                }
              </div>
          }
        </div>
      )}

      {/* Scanner availability hints */}
      <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 10, padding: '10px 14px', background: 'rgba(15,23,42,0.45)', fontSize: 12, color: '#64748b' }}>
        <span style={{ marginRight: 12 }}>Trivy: {scorecard?.trivy_available ? '✓' : '✗'}</span>
        <span style={{ marginRight: 12 }}>Semgrep: {scorecard?.semgrep_available ? '✓' : '✗'}</span>
        <span>Nuclei: {scorecard?.nuclei_available ? '✓' : '✗'}</span>
      </div>
    </div>
  );
}

// ── Integration Health panel ─────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  healthy: '#22c55e',
  degraded: '#f59e0b',
  unhealthy: '#ef4444',
  not_configured: '#94a3b8',
  not_migrated: '#f59e0b',
};

function HealthDot({ status }: { status: string }) {
  const color = STATUS_COLORS[status] || '#94a3b8';
  return (
    <span style={{
      display: 'inline-block', width: 10, height: 10,
      borderRadius: '50%', background: color, marginRight: 6,
      boxShadow: `0 0 6px ${color}88`,
    }} />
  );
}

function IntegrationHealthTab() {
  const [data, setData] = useState<any>(null);
  const [sourceHealth, setSourceHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const [json, sources] = await Promise.all([
        adminGet(`/api/v1/admin/integration-health${force ? '?force=true' : ''}`),
        adminGet('/api/v1/admin/bi/executive-metrics/source-health'),
      ]);
      setData(json);
      setSourceHealth(sources);
      setLastRefresh(new Date());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const deps = data?.dependencies || {};
  const cards = [
    { key: 'db', label: 'PostgreSQL', icon: '🗄' },
    { key: 'redis', label: 'Redis', icon: '⚡' },
    { key: 'ollama', label: 'Ollama LLM', icon: '🤖' },
    { key: 'pgvector', label: 'pgvector', icon: '🔍' },
    { key: 'cv_provider', label: 'CV Provider', icon: '👁' },
  ];

  if (loading && !data) return <div style={{ padding: 32, color: '#94a3b8' }}>Probing integrations…</div>;

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Integration Health</h2>
          {lastRefresh && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
              Last probed: {lastRefresh.toLocaleTimeString()}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span style={{
            padding: '4px 12px', borderRadius: 8, fontSize: 13, fontWeight: 600,
            background: data?.overall === 'healthy' ? '#14532d' : '#451a03',
            color: data?.overall === 'healthy' ? '#22c55e' : '#f59e0b',
          }}>
            {(data?.overall || 'unknown').toUpperCase()}
          </span>
          <button onClick={() => refresh(true)} style={{
            padding: '4px 14px', borderRadius: 8, fontSize: 13, cursor: 'pointer',
            background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)', color: '#a5b4fc',
          }}>
            Force refresh
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {cards.map(({ key, label, icon }) => {
          const dep = deps[key] || {};
          const status: string = dep.status || 'unknown';
          const color = STATUS_COLORS[status] || '#94a3b8';
          return (
            <div key={key} style={{
              flex: '1 1 200px', minWidth: 200,
              border: `1px solid ${color}44`,
              borderRadius: 12, padding: '16px 18px',
              background: 'rgba(15,23,42,0.5)',
            }}>
              <div style={{ fontSize: 20, marginBottom: 6 }}>{icon}</div>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{label}</div>
              <div style={{ display: 'flex', alignItems: 'center', fontSize: 13, marginBottom: 8 }}>
                <HealthDot status={status} />
                <span style={{ color, fontWeight: 500 }}>{status}</span>
              </div>
              {dep.latency_ms != null && (
                <div style={{ fontSize: 11, color: '#64748b' }}>Latency: {dep.latency_ms}ms</div>
              )}
              {dep.models && dep.models.length > 0 && (
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
                  Models: {dep.models.slice(0, 3).join(', ')}
                </div>
              )}
              {dep.provider && (
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
                  Provider: {dep.provider}{dep.model ? ` / ${dep.model}` : ''}
                </div>
              )}
              {dep.indexed_vectors != null && (
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
                  Vectors indexed: {dep.indexed_vectors.toLocaleString()}
                </div>
              )}
              {dep.error && (
                <div style={{ fontSize: 11, color: '#f87171', marginTop: 4, wordBreak: 'break-word' }}>
                  {dep.error}
                </div>
              )}
              {dep.note && (
                <div style={{ fontSize: 11, color: '#f59e0b', marginTop: 4 }}>{dep.note}</div>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 22 }}>
        <h3 style={{ fontSize: 15, margin: '0 0 10px' }}>Governed commerce feeds</h3>
        <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 10 }}>
          Tenant-scoped active facts and quarantined records. This view is read-only.
        </div>
        {(sourceHealth?.sources || []).length === 0 ? (
          <div style={{ color: '#f59e0b', fontSize: 13 }}>
            No canonical ERP, WMS, supplier or consented marketing facts are available.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {(sourceHealth.sources || []).map((source: any) => (
              <div key={`${source.family}:${source.source_system}`} style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(160px, 1fr) minmax(120px, 1fr) 90px 90px minmax(150px, 1fr)',
                gap: 10,
                alignItems: 'center',
                border: '1px solid rgba(148,163,184,0.18)',
                borderRadius: 8,
                padding: '9px 11px',
                background: 'rgba(15,23,42,0.45)',
                fontSize: 12,
              }}>
                <strong>{source.family}</strong>
                <span>{source.source_system}</span>
                <span>{source.active_records} active</span>
                <span style={{ color: source.quarantined_records ? '#f59e0b' : '#94a3b8' }}>
                  {source.quarantined_records} held
                </span>
                <span style={{ color: source.status === 'healthy' ? '#22c55e' : '#f59e0b' }}>
                  {source.status}{source.age_hours != null ? ` · ${source.age_hours}h old` : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div style={{ marginTop: 22 }}>
        <h3 style={{ fontSize: 15, margin: '0 0 10px' }}>Source onboarding</h3>
        <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 10 }}>
          Evidence contracts required before business metrics or governed actions can become available.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
          {(sourceHealth?.onboarding || []).map((source: any) => (
            <div key={source.family} style={{
              border: '1px solid rgba(148,163,184,0.18)',
              borderRadius: 8,
              padding: '11px 12px',
              background: 'rgba(15,23,42,0.45)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <strong style={{ fontSize: 13 }}>{source.label}</strong>
                <span style={{
                  color: source.status === 'connected' ? '#22c55e' : '#f59e0b',
                  fontSize: 11, whiteSpace: 'nowrap',
                }}>
                  {source.status === 'connected' ? 'Connected' : 'Not configured'}
                </span>
              </div>
              <div style={{ color: '#94a3b8', fontSize: 11, marginTop: 7 }}>
                Enables: {(source.required_for || []).join(', ')}
              </div>
              <details style={{ marginTop: 7, fontSize: 11, color: '#cbd5e1' }}>
                <summary style={{ cursor: 'pointer' }}>Required evidence</summary>
                <div style={{ marginTop: 5, color: '#94a3b8' }}>
                  {(source.required_fields || []).join(' · ')}
                </div>
              </details>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [idleLocked, setIdleLocked] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const j = await adminGet('/api/v1/admin/me');
        if (!mounted) return;
        setAuthorized(Boolean(j?.role));
      } catch {
        if (!mounted) return;
        setAuthorized(false);
      } finally {
        if (mounted) setAuthChecked(true);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let lastActivity = Date.now();
    const timeoutMs = 10 * 60 * 1000;
    const markActive = () => {
      lastActivity = Date.now();
      setIdleLocked(false);
    };
    const checkIdle = () => {
      if (Date.now() - lastActivity >= timeoutMs) setIdleLocked(true);
    };
    const events: Array<keyof WindowEventMap> = ['mousemove', 'keydown', 'click', 'scroll'];
    events.forEach((eventName) => window.addEventListener(eventName, markActive, { passive: true }));
    const timer = window.setInterval(checkIdle, 15000);
    return () => {
      window.clearInterval(timer);
      events.forEach((eventName) => window.removeEventListener(eventName, markActive));
    };
  }, []);

  const renderTab = () => {
    switch (activeTab) {
      case 'overview': return <OverviewTab />;
      case 'nqe': return <NQEAnalyticsTab />;
      case 'recommendations': return <RecommendationTab />;
      case 'fraud': return <FraudSecurityTab />;
      case 'supply_chain': return <SupplyChainTab />;
      case 'intelligence': return <IntelligenceTab />;
      case 'persona': return <PersonaIntelligenceTab />;
      case 'security_scorecard': return <SecurityScorecardTab />;
      case 'integration_health': return <IntegrationHealthTab />;
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0b1220',
      color: '#e5e7eb',
      fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif',
    }}>
      {!authChecked ? (
        <div style={{ padding: 24 }}>Authorizing admin session...</div>
      ) : !authorized ? (
        <div style={{ padding: 24, maxWidth: 560 }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Admin Session Not Authorized</div>
          <div style={{ color: '#94a3b8', fontSize: 13 }}>
            This dashboard now requires a valid server-side admin session or owner key. Browser state alone is not enough.
          </div>
        </div>
      ) : (
      <>
      <header style={{
        padding: '12px 16px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'linear-gradient(90deg, #0b1220, #101a33)',
        borderBottom: '1px solid rgba(148,163,184,0.2)',
      }}>
        <div>
          <div style={{ fontWeight: 700, letterSpacing: 0.2 }}>ShopSquire Admin Dashboard</div>
          <div style={{ color: '#94a3b8', fontSize: 12 }}>Full-stack intelligence metrics</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <a href="/merchant/dashboard" target="_blank" rel="noreferrer" style={{
            color: '#e5e7eb', textDecoration: 'none', border: '1px solid rgba(148,163,184,0.25)',
            padding: '6px 10px', borderRadius: 10, fontSize: 12,
          }}>Merchant FAQs</a>
          <a href="/merchant/bi" target="_blank" rel="noreferrer" style={{
            color: '#e5e7eb', textDecoration: 'none', border: '1px solid rgba(148,163,184,0.25)',
            padding: '6px 10px', borderRadius: 10, fontSize: 12,
          }}>Grafana BI</a>
        </div>
      </header>

      <div style={{
        display: 'flex', gap: 8, flexWrap: 'wrap',
        padding: '10px 16px',
        background: 'rgba(15,23,42,0.35)',
        borderBottom: '1px solid rgba(148,163,184,0.15)',
      }}>
        {TAB_CONFIG.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: activeTab === tab.id ? 'rgba(249,115,22,0.12)' : 'rgba(15,23,42,0.85)',
              color: '#e5e7eb',
              border: `1px solid ${activeTab === tab.id ? 'rgba(249,115,22,0.65)' : 'rgba(148,163,184,0.2)'}`,
              borderRadius: 10,
              padding: '8px 12px',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: activeTab === tab.id ? 600 : 400,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ padding: 16 }}>
        {idleLocked ? (
          <div style={{
            border: '1px solid rgba(248,113,113,0.3)',
            borderRadius: 14,
            padding: 18,
            background: 'rgba(15,23,42,0.72)',
            maxWidth: 520,
          }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Admin Session Locked</div>
            <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 12 }}>
              Inactivity paused live polling and hid privileged dashboards. Interact with the page to resume.
            </div>
            <button
              onClick={() => setIdleLocked(false)}
              style={{
                padding: '8px 12px',
                borderRadius: 10,
                cursor: 'pointer',
                border: '1px solid rgba(148,163,184,0.25)',
                background: 'rgba(15,23,42,0.85)',
                color: '#e5e7eb',
              }}
            >
              Resume Session
            </button>
          </div>
        ) : renderTab()}
      </div>
      </>
      )}
    </div>
  );
}
