import React, { useEffect, useState, useCallback } from 'react';
import {
  fetchAgentTrust,
  fetchCitationMemoryStats,
  fetchObservationSummary,
  fetchTrustedClaims,
  fetchUserBehavioralModel,
  fetchUserProfile,
} from '../api';

interface CitationStats {
  total_claims: number;
  verified_claims: number;
  correct_claims: number;
  accuracy_rate: number;
  avg_trust_score: number;
  pending_claims: number;
}

interface BehavioralModel {
  decision_style: string;
  comparison_style: string;
  avg_turns_per_session: number;
  avg_products_compared: number;
  recurring_constraints: Record<string, number>;
}

interface TrustedClaim {
  agent_name: string;
  claim_type: string;
  claim_key: string;
  claim_value: string;
  trust_score: number;
  confidence: number;
}

interface ObservationSummary {
  compressed_at?: number;
  total_events?: number;
  event_types?: Record<string, any>;
}

function CitationMemorySection() {
  const [stats, setStats] = useState<CitationStats | null>(null);
  const [claims, setClaims] = useState<TrustedClaim[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      fetchCitationMemoryStats(),
      fetchTrustedClaims({ minTrust: 0.6, limit: 20 }),
    ]).then(([s, c]) => {
      if (s.status === 'fulfilled') setStats(s.value);
      if (c.status === 'fulfilled') setClaims(Array.isArray(c.value) ? c.value : []);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="callout">Loading citation memory...</div>;

  return (
    <>
      <h3 className="section-title">Citation Memory - Layer 4</h3>
      <div className="card-row">
        <div className="stat-card">
          <div className="stat-label">Total Claims</div>
          <div className="stat-value">{stats?.total_claims ?? '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Verified</div>
          <div className="stat-value">{stats?.verified_claims ?? '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Accuracy Rate</div>
          <div className="stat-value">
            {stats ? `${(stats.accuracy_rate * 100).toFixed(1)}%` : '-'}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Avg Trust Score</div>
          <div className="stat-value">{stats?.avg_trust_score?.toFixed(3) ?? '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Pending</div>
          <div className="stat-value">{stats?.pending_claims ?? '-'}</div>
        </div>
      </div>

      {claims.length > 0 && (
        <div className="card" style={{ marginTop: 12 }}>
          <h4 className="card-title">High-Trust Agent Claims</h4>
          <table className="table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Type</th>
                <th>Key</th>
                <th>Trust</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim, i) => (
                <tr key={i}>
                  <td>{claim.agent_name}</td>
                  <td><span className="pill">{claim.claim_type}</span></td>
                  <td>{claim.claim_key}</td>
                  <td>{claim.trust_score.toFixed(3)}</td>
                  <td>{claim.confidence.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function UserProfileLookup() {
  const [userId, setUserId] = useState('');
  const [profile, setProfile] = useState<any>(null);
  const [behavioral, setBehavioral] = useState<BehavioralModel | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const lookup = useCallback(async () => {
    if (!userId.trim()) return;
    setLoading(true);
    setError('');
    try {
      const [profileData, behavioralData] = await Promise.all([
        fetchUserProfile(userId),
        fetchUserBehavioralModel(userId),
      ]);
      setProfile(profileData);
      setBehavioral(behavioralData);
    } catch (e: any) {
      setError(e?.message || 'Not found');
      setProfile(null);
      setBehavioral(null);
    }
    setLoading(false);
  }, [userId]);

  return (
    <>
      <h3 className="section-title">Returning Customer Profile Lookup</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          className="modal-input"
          placeholder="Enter user ID"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && lookup()}
          style={{ maxWidth: 280 }}
        />
        <button className="btn" onClick={lookup} disabled={loading}>
          {loading ? 'Loading...' : 'Lookup'}
        </button>
      </div>
      {error && <div className="callout" style={{ color: '#ef4444' }}>{error}</div>}
      {profile?.found && (
        <div className="card">
          <h4 className="card-title">User: {userId}</h4>
          <div className="card-row" style={{ flexWrap: 'wrap' }}>
            <div className="stat-card">
              <div className="stat-label">Budget Tier</div>
              <div className="stat-value">{profile.budget_tier || '-'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Preferred Brands</div>
              <div className="stat-value" style={{ fontSize: 13 }}>{(profile.preferred_brands || []).join(', ') || '-'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Avoided Brands</div>
              <div className="stat-value" style={{ fontSize: 13 }}>{(profile.avoided_brands || []).join(', ') || '-'}</div>
            </div>
          </div>
          {behavioral && (
            <div style={{ marginTop: 12 }}>
              <h4 className="card-title">Behavioral Model</h4>
              <div className="card-row" style={{ flexWrap: 'wrap' }}>
                <div className="stat-card">
                  <div className="stat-label">Decision Style</div>
                  <div className="stat-value" style={{ fontSize: 14 }}>{behavioral.decision_style}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Comparison Style</div>
                  <div className="stat-value" style={{ fontSize: 14 }}>{behavioral.comparison_style}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Avg Turns</div>
                  <div className="stat-value">{behavioral.avg_turns_per_session?.toFixed(1) || '-'}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Avg Products</div>
                  <div className="stat-value">{behavioral.avg_products_compared?.toFixed(1) || '-'}</div>
                </div>
              </div>
              {behavioral.recurring_constraints && Object.keys(behavioral.recurring_constraints).length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <strong style={{ fontSize: 12 }}>Recurring Constraints:</strong>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                    {Object.entries(behavioral.recurring_constraints).map(([k, v]) => (
                      <span key={k} className="pill">{k}: {v}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function ObservationSummarySection() {
  const [sessionId, setSessionId] = useState('');
  const [summary, setSummary] = useState<ObservationSummary | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!sessionId.trim()) return;
    setError('');
    try {
      const data = await fetchObservationSummary(sessionId);
      setSummary(data?.summary || null);
    } catch (e: any) {
      setError(e?.message || 'Not found');
      setSummary(null);
    }
  }, [sessionId]);

  return (
    <>
      <h3 className="section-title">Observation Summary - Layer 2</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          className="modal-input"
          placeholder="Session ID"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          style={{ maxWidth: 280 }}
        />
        <button className="btn" onClick={load}>Load</button>
      </div>
      {error && <div className="callout" style={{ color: '#ef4444' }}>{error}</div>}
      {summary && (
        <div className="card">
          <div className="card-row" style={{ flexWrap: 'wrap' }}>
            <div className="stat-card">
              <div className="stat-label">Total Events</div>
              <div className="stat-value">{summary.total_events ?? 0}</div>
            </div>
          </div>
          {summary.event_types && Object.entries(summary.event_types).map(([type, data]) => (
            <div key={type} style={{ marginTop: 8 }}>
              <strong style={{ fontSize: 12 }}>{type}</strong>: {(data as any)?.count ?? 0} events
              {(data as any)?.models_used && (
                <span style={{ marginLeft: 8, opacity: 0.7, fontSize: 12 }}>
                  models: {Object.keys((data as any).models_used).join(', ')}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function AgentTrustSection() {
  const [agentName, setAgentName] = useState('');
  const [trust, setTrust] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!agentName.trim()) return;
    try {
      const data = await fetchAgentTrust(agentName);
      setTrust(data?.trust_score ?? null);
    } catch {
      setTrust(null);
    }
  }, [agentName]);

  return (
    <>
      <h3 className="section-title">Agent Trust Lookup</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          className="modal-input"
          placeholder="Agent name (e.g. fraud_scorer)"
          value={agentName}
          onChange={(e) => setAgentName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          style={{ maxWidth: 280 }}
        />
        <button className="btn" onClick={load}>Check Trust</button>
      </div>
      {trust !== null && (
        <div className="card">
          <div className="stat-card">
            <div className="stat-label">{agentName} Trust Score</div>
            <div className="stat-value">{trust.toFixed(4)}</div>
          </div>
        </div>
      )}
    </>
  );
}

export function AgentIntelligence({ role }: { role: string }) {
  return (
    <div>
      <CitationMemorySection />
      <div style={{ marginTop: 24 }} />
      <UserProfileLookup />
      <div style={{ marginTop: 24 }} />
      <ObservationSummarySection />
      <div style={{ marginTop: 24 }} />
      <AgentTrustSection />
    </div>
  );
}
