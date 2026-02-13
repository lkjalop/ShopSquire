import React from 'react';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function GrafanaDashboards({ role }: Props) {
  const grafanaProxyBase = (import.meta.env.VITE_GRAFANA_PROXY_BASE as string) || '/admin/grafana_proxy';
  const base = grafanaProxyBase.replace(/\/$/, '');

  const dashboards = [
    {
      title: 'Executive Overview',
      uid: 'shopsquire-exec-overview',
      panelId: 2,
      panels: 14,
      file: 'shopsquire-executive-overview.json',
      features: 'KPIs, agent activity, security events, health status',
    },
    {
      title: 'Agent Confidence',
      uid: 'shopsquire-agent-confidence',
      panelId: 2,
      panels: 12,
      file: 'shopsquire-agent-confidence.json',
      features: 'Histogram, calibration, low-conf samples with drill-down',
    },
    {
      title: 'CV Latency',
      uid: 'shopsquire-cv-latency',
      panelId: 2,
      panels: 11,
      file: 'shopsquire-cv-latency.json',
      features: 'T0/T1/T2 breakdown, slow requests table',
    },
    {
      title: 'Escalation Rates',
      uid: 'shopsquire-escalation-rates',
      panelId: 2,
      panels: 10,
      file: 'shopsquire-escalation-rates.json',
      features: 'By agent/reason, pending queue with actions',
    },
    {
      title: 'RAGAS Over Time',
      uid: 'shopsquire-ragas',
      panelId: 2,
      panels: 11,
      file: 'shopsquire-ragas-over-time.json',
      features: '4 RAGAS metrics, CI guard, low-score drill-down',
    },
    {
      title: 'Model Selection',
      uid: 'shopsquire-model-selection',
      panelId: 2,
      panels: 11,
      file: 'shopsquire-model-selection.json',
      features: 'Tier distribution, cost savings, T2 escalation reasons',
    },
    {
      title: 'Query Cluster Drift',
      uid: 'shopsquire-query-cluster-drift',
      panelId: 2,
      panels: 11,
      file: 'shopsquire-query-cluster-drift.json',
      features: 'Volume trends, drift score, new clusters',
    },
    {
      title: 'Human Review Queue',
      uid: 'shopsquire-human-review',
      panelId: 2,
      panels: 10,
      file: 'shopsquire-human-review-queue.json',
      features: 'Pending table with priority colors, outcomes',
    },
  ];

  return (
    <div className="stagger">
      <div className="card">
        <h3>Grafana Dashboards</h3>
        <div className="page-sub" style={{ marginTop: 6 }}>
          Embedded via the Grafana proxy for secure access. Choose a dashboard for full drill-down.
        </div>
        <div className="grid-2" style={{ marginTop: 12 }}>
          {dashboards.map((d) => {
            const panelSrc = `${base}/d-solo/${d.uid}?orgId=1&panelId=${d.panelId}&from=now-24h&to=now&theme=dark&var-theme=dark`;
            const dashHref = `${base}/d/${d.uid}?orgId=1&theme=dark&var-theme=dark`;
            return (
              <div className="card" key={d.uid} style={{ padding: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                  <h4 style={{ margin: 0 }}>{d.title}</h4>
                  <span className="page-sub">{d.panels} panels</span>
                </div>
                <div className="page-sub" style={{ marginTop: 6 }}>{d.features}</div>
                <iframe
                  src={panelSrc}
                  title={`${d.title} preview`}
                  style={{ width: '100%', height: 220, border: '1px solid rgba(255,255,255,0.08)', marginTop: 10 }}
                  loading="lazy"
                />
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
                  <a className="btn secondary" href={dashHref} target="_blank" rel="noreferrer">Open dashboard</a>
                  <span className="page-sub">file: {d.file}</span>
                </div>
              </div>
            );
          })}
        </div>
        {role === 'merchant' && (
          <div className="callout" style={{ marginTop: 12 }}>
            Some dashboards may require Owner or Developer access depending on your Grafana permissions.
          </div>
        )}
      </div>
    </div>
  );
}
