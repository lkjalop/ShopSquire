import React, { useEffect, useState } from 'react';
import { fetchAnalytics } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function Analytics({ role }: Props) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    setLoading(true);
    setError('');
    fetchAnalytics(days)
      .then(setData)
      .catch(() => setError('Failed to load analytics.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, [days]);

  const series = data?.series || {};

  return (
    <div className="stagger">
      <div className="panel">
        <strong>Time Range</strong>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          {[7, 30, 90].map((d) => (
            <button key={d} className={`btn ${days === d ? '' : 'secondary'}`} onClick={() => setDays(d)}>
              Last {d} days
            </button>
          ))}
        </div>
        {loading && <div className="page-sub" style={{ marginTop: 8 }}>Loading analytics...</div>}
        {error && <div className="page-sub" style={{ marginTop: 8, color: '#9f2d1b' }}>{error}</div>}
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Orders</h3>
          <div className="chart">
            <div className="bar-chart">
              {(series.orders || []).map((p: any) => (
                <div key={p.day} className="bar">
                  <div className="bar-fill" style={{ height: `${Math.max(6, (p.count / Math.max(...(series.orders || []).map((s: any) => s.count), 1)) * 100)}%` }} />
                  <span>{new Date(p.day).toLocaleDateString(undefined, { weekday: 'short' })}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="card">
          <h3>Decisions</h3>
          <div className="chart">
            <div className="bar-chart">
              {(series.decisions || []).map((p: any) => (
                <div key={p.day} className="bar">
                  <div className="bar-fill" style={{ height: `${Math.max(6, (p.count / Math.max(...(series.decisions || []).map((s: any) => s.count), 1)) * 100)}%` }} />
                  <span>{new Date(p.day).toLocaleDateString(undefined, { weekday: 'short' })}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Security Events</h3>
        <div className="chart">
          <div className="bar-chart">
            {(series.security || []).map((p: any) => (
              <div key={p.day} className="bar">
                <div className="bar-fill" style={{ height: `${Math.max(6, (p.count / Math.max(...(series.security || []).map((s: any) => s.count), 1)) * 100)}%` }} />
                <span>{new Date(p.day).toLocaleDateString(undefined, { weekday: 'short' })}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

    </div>
  );
}
