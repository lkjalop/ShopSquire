import { useEffect, useState, useCallback } from 'react';
import { apiUrl, safeJson } from '../lib/api';

type TabId = 'overview' | 'nqe' | 'recommendations' | 'fraud' | 'supply_chain' | 'intelligence';

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
];

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
        const r = await fetch(apiUrl('/status/summary'));
        const j = await safeJson(r);
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
            ['RAGAS Summary', '/api/v1/analytics/ragas/summary'],
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
        const r = await fetch(apiUrl('/api/v1/analytics/query_clusters/latest?limit=15'));
        const j = await safeJson(r);
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
  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Recommendation Performance</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <MetricCardComponent card={{ label: 'Recommendations (24h)', value: '-', trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Avg Confidence', value: '-', trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Debate Triggers', value: '-', trend: 'flat' }} />
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Recommendation Acceptance (coming soon)</div>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          CTR per product, "why" code breakdown, and debate outcomes will appear here when data flows through the pipeline.
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
        const r = await fetch(apiUrl('/api/v1/merchant/intelligence/citation_memory/stats'));
        const j = await safeJson(r);
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
  return (
    <div>
      <h3 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600 }}>Supply Chain Health</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <MetricCardComponent card={{ label: 'Provider Health', value: '-', trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Schema Errors', value: '-', trend: 'flat' }} />
        <MetricCardComponent card={{ label: 'Anomaly Flags', value: '-', trend: 'flat' }} />
      </div>
      <div style={{
        border: '1px solid rgba(148,163,184,0.18)',
        borderRadius: 12, background: 'rgba(15,23,42,0.45)', padding: 14,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Provider Anomaly Detection</div>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          Supply chain monitoring dashboard with real-time provider telemetry.
          Use <a href="/api/v1/admin/supply_chain/anomalies/default" target="_blank" style={{ color: '#60a5fa' }}>
            API endpoint
          </a> for live data.
        </div>
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
      const r = await fetch(apiUrl(`/api/v1/merchant/intelligence/user_profiles/${encodeURIComponent(profileId)}`));
      const j = await safeJson(r);
      setProfile(j);
      const r2 = await fetch(apiUrl(`/api/v1/merchant/intelligence/user_profiles/${encodeURIComponent(profileId)}/behavioral_model`));
      const j2 = await safeJson(r2);
      setBehavioral(j2);
    } catch { setProfile(null); setBehavioral(null); }
  }, [profileId]);

  const loadObservation = useCallback(async () => {
    if (!obsSessionId.trim()) return;
    try {
      const r = await fetch(apiUrl(`/api/v1/merchant/intelligence/observation_summary/${encodeURIComponent(obsSessionId)}`));
      const j = await safeJson(r);
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

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState<TabId>('overview');

  const renderTab = () => {
    switch (activeTab) {
      case 'overview': return <OverviewTab />;
      case 'nqe': return <NQEAnalyticsTab />;
      case 'recommendations': return <RecommendationTab />;
      case 'fraud': return <FraudSecurityTab />;
      case 'supply_chain': return <SupplyChainTab />;
      case 'intelligence': return <IntelligenceTab />;
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0b1220',
      color: '#e5e7eb',
      fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif',
    }}>
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
        {renderTab()}
      </div>
    </div>
  );
}
