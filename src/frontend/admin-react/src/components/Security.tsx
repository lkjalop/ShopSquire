import React, { useEffect, useState } from 'react';
import { fetchSecurityEvents, fetchSecurityEventsFiltered, fetchSecurityMetrics, fetchSupplyChainStatus, fetchIamEvents, fetchAbacDenySummary, fetchSecurityAttackTimeseries, fetchSecurityGeoAsnTrends, type AbacDenyGroup, type SecurityAttackBucket, type SecurityGeoAsnTrend, type SecurityEvent, escalateEvent, blockEvent, sendAlertmanagerTest, fetchEmailSecurityIncidents, type EmailSecurityIncident, getEmailSecurityIncident, fetchUpsellPerformance, type UpsellPerformance, fetchSecurityEscalationSummary, type SecurityEscalationSummary, fetchSupplierRiskSummary, fetchInventoryDriftCheck, fetchNetworkProbeSummary, fetchKillchainProgression, fetchEmailIocFeedbackQuality, fetchIncidentAlertSummary, type IncidentAlertSummary } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function Security({ role }: Props) {
  const grafanaUrl = 'http://localhost:3000/d/shopsquire-overview?viewPanel=25';
  const [selected, setSelected] = useState<SecurityEvent | null>(null);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<any | null>(null);
  const [upsellPerf, setUpsellPerf] = useState<UpsellPerformance | null>(null);
  const [escalationSummary, setEscalationSummary] = useState<SecurityEscalationSummary | null>(null);
  const [supplierRisk, setSupplierRisk] = useState<any | null>(null);
  const [inventoryDrift, setInventoryDrift] = useState<any | null>(null);
  const [networkProbes, setNetworkProbes] = useState<any | null>(null);
  const [killchain, setKillchain] = useState<any | null>(null);
  const [iocQuality, setIocQuality] = useState<any | null>(null);
  const [incidentAlerts, setIncidentAlerts] = useState<IncidentAlertSummary | null>(null);
  const [compactLoading, setCompactLoading] = useState(false);
  const [compactError, setCompactError] = useState<string | null>(null);
  const [supplyChain, setSupplyChain] = useState<any | null>(null);
  const [severity, setSeverity] = useState('all');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [iamEvents, setIamEvents] = useState<any[]>([]);
  const [alertSending, setAlertSending] = useState(false);
  const [alertStatus, setAlertStatus] = useState<string | null>(null);
  const [alertError, setAlertError] = useState<string | null>(null);
  const [abacGroups, setAbacGroups] = useState<AbacDenyGroup[]>([]);
  const [abacTotal, setAbacTotal] = useState(0);
  const [abacLoading, setAbacLoading] = useState(false);
  const [abacError, setAbacError] = useState<string | null>(null);
  const [attackTotals, setAttackTotals] = useState<{ security_type: string; count: number }[]>([]);
  const [attackRecentBuckets, setAttackRecentBuckets] = useState<SecurityAttackBucket[]>([]);
  const [attackLoading, setAttackLoading] = useState(false);
  const [attackError, setAttackError] = useState<string | null>(null);
  const [geoTrends, setGeoTrends] = useState<SecurityGeoAsnTrend[]>([]);
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  // Email security incidents
  const [emailIncidents, setEmailIncidents] = useState<EmailSecurityIncident[]>([]);
  const [emailIncLoading, setEmailIncLoading] = useState(false);
  const [emailIncError, setEmailIncError] = useState<string | null>(null);
  const [emailIncSeverity, setEmailIncSeverity] = useState<string>('all');
  const [emailIncImportantOnly, setEmailIncImportantOnly] = useState<boolean>(true);
  const [emailIncSelected, setEmailIncSelected] = useState<EmailSecurityIncident | null>(null);
  const formatTs = (ts: any) => {
    if (!ts) return '-';
    const num = typeof ts === 'number' ? ts : Number(ts);
    if (!Number.isFinite(num)) return '-';
    return new Date(num * 1000).toLocaleString();
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([fetchSecurityEvents(), fetchSecurityMetrics(), fetchSupplyChainStatus(), fetchIamEvents(10)])
      .then(([eventsResp, metricsResp, supplyResp, iamResp]) => {
        if (!cancelled) {
          setEvents(eventsResp);
          setMetrics(metricsResp);
          setSupplyChain(supplyResp);
          setIamEvents(iamResp.events || []);
        }
      })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const loadCompact = async () => {
      setCompactLoading(true);
      setCompactError(null);
      try {
        const [upsell, sec, sup, drift, probes, kc, iocq, incAlerts] = await Promise.all([
          fetchUpsellPerformance(24, 5),
          fetchSecurityEscalationSummary(24, 2000),
          fetchSupplierRiskSummary(24 * 7),
          fetchInventoryDriftCheck(),
          fetchNetworkProbeSummary(24),
          fetchKillchainProgression(24),
          fetchEmailIocFeedbackQuality(),
          fetchIncidentAlertSummary(24, 20),
        ]);
        if (cancelled) return;
        setUpsellPerf(upsell as any);
        setEscalationSummary(sec as any);
        setSupplierRisk(sup as any);
        setInventoryDrift(drift as any);
        setNetworkProbes(probes as any);
        setKillchain(kc as any);
        setIocQuality(iocq as any);
        setIncidentAlerts(incAlerts as any);
      } catch (e: any) {
        if (!cancelled) setCompactError(e.message || 'Failed to load compact metrics');
      } finally {
        if (!cancelled) setCompactLoading(false);
      }
    };
    loadCompact();
    timer = setInterval(loadCompact, 20000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setEmailIncLoading(true);
    setEmailIncError(null);
    async function load() {
      try {
        if (emailIncImportantOnly) {
          const [warnRows, errRows] = await Promise.all([
            fetchEmailSecurityIncidents({ severity: 'warning', limit: 50, offset: 0 }),
            fetchEmailSecurityIncidents({ severity: 'error', limit: 50, offset: 0 }),
          ]);
          if (cancelled) return;
          const map = new Map<string, EmailSecurityIncident>();
          [...warnRows, ...errRows].forEach(r => map.set(r.id, r));
          const merged = Array.from(map.values()).sort((a, b) => (new Date(b.created_at||'').getTime()) - (new Date(a.created_at||'').getTime()));
          setEmailIncidents(merged.slice(0, 50));
        } else {
          const rows = await fetchEmailSecurityIncidents({ severity: emailIncSeverity === 'all' ? undefined : emailIncSeverity, limit: 50 });
          if (cancelled) return;
          setEmailIncidents(rows);
        }
      } catch (e: any) {
        if (!cancelled) setEmailIncError(e.message || 'Failed to load incidents');
      } finally {
        if (!cancelled) setEmailIncLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [emailIncSeverity, emailIncImportantOnly]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = async () => {
      setAbacLoading(true);
      setAbacError(null);
      try {
        const data = await fetchAbacDenySummary(24, 2000);
        if (cancelled) return;
        setAbacGroups(data.groups || []);
        setAbacTotal(Number(data.total_denies || 0));
      } catch (e: any) {
        if (!cancelled) setAbacError(e.message || 'Failed to load ABAC deny summary');
      } finally {
        if (!cancelled) setAbacLoading(false);
      }
    };
    load();
    timer = setInterval(load, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = async () => {
      setAttackLoading(true);
      setAttackError(null);
      try {
        const data = await fetchSecurityAttackTimeseries(24, 5000);
        if (cancelled) return;
        const totals = (data.totals_by_type || []).slice(0, 6);
        const recent = (data.buckets || []).slice(-8).reverse();
        setAttackTotals(totals);
        setAttackRecentBuckets(recent);
      } catch (e: any) {
        if (!cancelled) setAttackError(e.message || 'Failed to load attack trends');
      } finally {
        if (!cancelled) setAttackLoading(false);
      }
    };
    load();
    timer = setInterval(load, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = async () => {
      setGeoLoading(true);
      setGeoError(null);
      try {
        const data = await fetchSecurityGeoAsnTrends(24, 5000);
        if (cancelled) return;
        setGeoTrends((data.trends || []).slice(0, 8));
      } catch (e: any) {
        if (!cancelled) setGeoError(e.message || 'Failed to load ASN/Geo trends');
      } finally {
        if (!cancelled) setGeoLoading(false);
      }
    };
    load();
    timer = setInterval(load, 15000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  return (
    <div className="stagger">
      <div className="card">
        <h3>Filters</h3>
        <div className="grid-2">
          <div>
            <label className="page-sub">Severity</label>
            <select className="modal-input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="all">All</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="warn">Warn</option>
              <option value="info">Info</option>
            </select>
          </div>
          <div>
            <label className="page-sub">Time window (ISO)</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input className="modal-input" placeholder="since (YYYY-MM-DD)" value={since} onChange={(e) => setSince(e.target.value)} />
              <input className="modal-input" placeholder="until (YYYY-MM-DD)" value={until} onChange={(e) => setUntil(e.target.value)} />
              <button
                className="btn secondary"
                onClick={async () => {
                  setLoading(true);
                  try {
                    const rows = await fetchSecurityEventsFiltered({
                      severity: severity === 'all' ? undefined : severity,
                      since: since || undefined,
                      until: until || undefined,
                    });
                    setEvents(rows);
                  } catch (e: any) {
                    setError(e.message || 'Failed to filter');
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      </div>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Upsell Performance (24h)</h3>
          <div className="page-sub">Checkout recommendation quality and poison-guard impact.</div>
          {compactLoading && !upsellPerf && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
          {compactError && !upsellPerf && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>{compactError}</div>}
          {!!upsellPerf && (
            <div className="list" style={{ marginTop: 10 }}>
              <div className="list-item"><div>CTR</div><strong>{(upsellPerf.ctr * 100).toFixed(1)}%</strong></div>
              <div className="list-item"><div>Add-to-cart rate</div><strong>{(upsellPerf.add_to_cart_rate * 100).toFixed(1)}%</strong></div>
              <div className="list-item"><div>Blocked poisoned candidates</div><strong>{upsellPerf.blocked_poisoned_candidates}</strong></div>
              <div className="list-item"><div>Impressions / Clicks</div><strong>{upsellPerf.impressions} / {upsellPerf.clicks}</strong></div>
            </div>
          )}
          {!!upsellPerf?.top_skus?.length && (
            <div className="page-sub" style={{ marginTop: 8 }}>
              Top SKU: {upsellPerf.top_skus[0].sku} ({(upsellPerf.top_skus[0].ctr * 100).toFixed(1)}% CTR)
            </div>
          )}
        </div>
        <div className="card">
          <h3>Security Escalation + DREAD (24h)</h3>
          <div className="page-sub">Evidence-driven alert posture with trace drilldown anchors.</div>
          {compactLoading && !escalationSummary && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
          {compactError && !escalationSummary && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>{compactError}</div>}
          {!!escalationSummary && (
            <div className="list" style={{ marginTop: 10 }}>
              <div className="list-item"><div>Escalated / Blocked</div><strong>{escalationSummary.escalated} / {escalationSummary.blocked}</strong></div>
              <div className="list-item"><div>Escalation rate</div><strong>{(escalationSummary.escalation_rate * 100).toFixed(1)}%</strong></div>
              <div className="list-item"><div>DREAD avg / p95</div><strong>{escalationSummary.dread.avg} / {escalationSummary.dread.p95}</strong></div>
              <div className="list-item"><div>High DREAD alerts</div><strong>{escalationSummary.dread.high_count}</strong></div>
              <div className="list-item"><div>Evidence-rich events</div><strong>{escalationSummary.evidence.events_with_evidence}</strong></div>
            </div>
          )}
          {!!escalationSummary?.sample_trace_ids?.length && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              {escalationSummary.sample_trace_ids.slice(0, 3).map((tid) => (
                <a
                  key={tid}
                  className="btn ghost"
                  style={{ padding: '4px 8px', borderRadius: 10 }}
                  href={`/api/v1/admin/security/drilldown/${encodeURIComponent(tid)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Trace {tid.slice(0, 8)}
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h3>Incident Alert Loop (24h)</h3>
        <div className="page-sub">Explicit operational alerts for SLA breaches and runbook failures.</div>
        {compactLoading && !incidentAlerts && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
        {compactError && !incidentAlerts && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>{compactError}</div>}
        {!!incidentAlerts && (
          <>
            <div className="list" style={{ marginTop: 10 }}>
              <div className="list-item"><div>SLA breach alerts</div><strong>{incidentAlerts.totals?.sla_breach_alerts || 0}</strong></div>
              <div className="list-item"><div>Runbook failure alerts</div><strong>{incidentAlerts.totals?.runbook_failure_alerts || 0}</strong></div>
              <div className="list-item"><div>Impacted incidents</div><strong>{incidentAlerts.totals?.incidents_with_alerts || 0}</strong></div>
            </div>
            {!!incidentAlerts.recent?.length && (
              <table className="table" style={{ marginTop: 10 }}>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Incident</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Alerted</th>
                  </tr>
                </thead>
                <tbody>
                  {incidentAlerts.recent.slice(0, 6).map((a) => (
                    <tr key={`${a.type}:${a.incident_id}:${a.alerted_at || a.created_at || ''}`}>
                      <td>{a.type}</td>
                      <td>
                        <a href={`/admin?tab=escalations&incident=${encodeURIComponent(a.incident_id)}`}>{a.incident_id.slice(0, 12)}</a>
                      </td>
                      <td>{a.severity || '-'}</td>
                      <td>{a.status || '-'}</td>
                      <td>{a.alerted_at || a.created_at || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h3>Supplier Risk + Quarantine (7d)</h3>
        <div className="page-sub">Vendor trust from feed-delta anomalies; quarantined updates never reach live upsert.</div>
        {compactLoading && !supplierRisk && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
        {compactError && !supplierRisk && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>{compactError}</div>}
          {!!supplierRisk && (
            <div className="grid-2" style={{ marginTop: 10 }}>
            <div className="list">
              <div className="list-item"><div>Quarantined updates</div><strong>{supplierRisk.quarantined_updates || 0}</strong></div>
              <div className="list-item"><div>Average risk</div><strong>{Number(supplierRisk.avg_risk_score || 0).toFixed(3)}</strong></div>
              <div className="list-item"><div>Inventory drift status</div><strong>{inventoryDrift?.status || 'unknown'}</strong></div>
            </div>
            <div className="list">
              {(supplierRisk.source_risk || []).slice(0, 4).map((r: any) => (
                <div className="list-item" key={r.source}>
                  <div>{r.source}</div>
                  <strong>trust {Number(r.trust_score || 0).toFixed(2)} ({r.quarantined})</strong>
                </div>
              ))}
              {!(supplierRisk.source_risk || []).length && <div className="page-sub">No supplier anomalies in window.</div>}
            </div>
            </div>
          )}
          {!!inventoryDrift && (
            <div className="page-sub" style={{ marginTop: 8 }}>
              drift: missing_inv={inventoryDrift.missing_inventory_products || 0}, orphan_inv={inventoryDrift.orphan_inventory_rows || 0}, unknown_order_skus={inventoryDrift.unknown_order_line_skus || 0}
            </div>
          )}
      </div>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Network Probes (24h)</h3>
          <div className="list">
            <div className="list-item"><div>Total events</div><strong>{networkProbes?.total_events ?? 0}</strong></div>
            <div className="list-item"><div>High risk</div><strong>{networkProbes?.high_risk_events ?? 0}</strong></div>
            <div className="list-item"><div>Recon stage</div><strong>{networkProbes?.by_stage?.Recon ?? 0}</strong></div>
            <div className="list-item"><div>Exploitation stage</div><strong>{networkProbes?.by_stage?.Exploitation ?? 0}</strong></div>
          </div>
        </div>
        <div className="card">
          <h3>Kill Chain Progression</h3>
          <div className="list">
            {Object.entries(killchain?.stage_counts || {}).slice(0, 6).map(([k, v]: any) => (
              <div className="list-item" key={k}><div>{k}</div><strong>{v}</strong></div>
            ))}
            {!Object.keys(killchain?.stage_counts || {}).length && <div className="page-sub">No kill-chain stage data.</div>}
          </div>
          {killchain?.escalation_recommended && <div className="page-sub" style={{ color: '#9f2d1b', marginTop: 8 }}>Escalation recommended: stage chaining detected.</div>}
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h3>IOC Quality Feedback</h3>
        <div className="page-sub">False positive/negative feedback by IOC source type for threshold tuning.</div>
        {!!(iocQuality?.items || []).length && (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>IOC Type</th>
                <th>Labels</th>
                <th>FP Rate</th>
                <th>FN Rate</th>
                <th>Precision</th>
              </tr>
            </thead>
            <tbody>
              {(iocQuality.items || []).slice(0, 8).map((r: any) => (
                <tr key={r.ioc_type}>
                  <td>{r.ioc_type}</td>
                  <td>{r.labels_total}</td>
                  <td>{(Number(r.false_positive_rate || 0) * 100).toFixed(1)}%</td>
                  <td>{(Number(r.false_negative_rate || 0) * 100).toFixed(1)}%</td>
                  <td>{(Number(r.precision_proxy || 0) * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!(iocQuality?.items || []).length && <div className="page-sub" style={{ marginTop: 10 }}>No IOC feedback labels yet.</div>}
      </div>
      <div className="grid-2">
        <div className="card">
          <h3>Threat Distribution</h3>
          <div className="list">
            <div className="list-item"><div>AML.T0043 Prompt Injection</div><strong>26</strong></div>
            <div className="list-item"><div>AML.T0020 Supply Chain</div><strong>3</strong></div>
            <div className="list-item"><div>AML.T0048 Data Exfil</div><strong>1</strong></div>
          </div>
        </div>
        <div className="card">
          <h3>Response Readiness</h3>
          <div className="list">
            <div className="list-item"><div>Kill switch</div><span className="badge">Armed</span></div>
            <div className="list-item"><div>Escalation SLA</div><strong>8 min</strong></div>
            <div className="list-item"><div>Active playbooks</div><strong>5</strong></div>
          </div>
        </div>
      </div>

                  <div className="card" style={{ marginTop: 14 }}>
        <h3>Security Metrics (last {metrics?.window_hours || 24}h)</h3>
        <div className="grid-2">
          <div className="list">
            <div className="list-item"><div>Total events</div><strong>{metrics?.total ?? '-'}</strong></div>
            <div className="list-item"><div>Critical</div><strong>{metrics?.by_severity?.critical ?? 0}</strong></div>
            <div className="list-item"><div>High</div><strong>{metrics?.by_severity?.high ?? 0}</strong></div>
            <div className="list-item"><div>Warn</div><strong>{metrics?.by_severity?.warn ?? 0}</strong></div>
            <div className="list-item"><div>Info</div><strong>{metrics?.by_severity?.info ?? 0}</strong></div>
          </div>
          <div className="list">
            <div className="list-item"><div>Escalated</div><strong>{metrics?.escalated ?? 0}</strong></div>
            <div className="list-item"><div>Blocked</div><strong>{metrics?.blocked ?? 0}</strong></div>
            <div className="list-item"><div>Supply chain</div><strong>{metrics?.supply_chain ?? 0}</strong></div>
            <div className="list-item"><div>Latest event</div><strong>{metrics?.latest_event ?? '-'}</strong></div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
          <button
            className="btn secondary"
            disabled={alertSending}
            onClick={async () => {
              setAlertSending(true);
              setAlertStatus(null);
              setAlertError(null);
              try {
                const resp = await sendAlertmanagerTest();
                setAlertStatus(resp?.sent ? `Sent to ${resp.alertmanager_url || 'AlertManager'}` : 'Sent');
                const [eventsResp, metricsResp] = await Promise.all([
                  fetchSecurityEvents(),
                  fetchSecurityMetrics(),
                ]);
                setEvents(eventsResp);
                setMetrics(metricsResp);
              } catch (e: any) {
                setAlertError(e.message || 'Failed to send alert');
              } finally {
                setAlertSending(false);
              }
            }}
          >
            {alertSending ? 'Sending...' : 'Send test alert'}
          </button>
          {alertStatus && <span className="page-sub">{alertStatus}</span>}
          {alertError && <span className="page-sub" style={{ color: '#9f2d1b' }}>{alertError}</span>}
          <a className="btn ghost" href={grafanaUrl} target="_blank" rel="noreferrer">Open Grafana panel</a>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Supply Chain Status</h3>
        {!supplyChain?.vendors && <div className="page-sub">No data yet.</div>}
        {supplyChain?.vendors && (
          <div className="list">
            {Object.values(supplyChain.vendors).map((v: any) => (
              <div className="list-item" key={v.vendor}>
                <div>
                  {v.vendor} <span className="page-sub" style={{ marginLeft: 8 }}>{v.endpoint}</span>
                  <div className="page-sub" style={{ marginTop: 4 }}>
                    last check: {formatTs(v.checked_at)}
                    {v.issues && v.issues.length ? ` * issues: ${v.issues.join(', ')}` : ' * issues: none'}
                  </div>
                </div>
                <strong>{v.status || 'unknown'}</strong>
              </div>
            ))}
          </div>
        )}
      </div>

<div className="card" style={{ marginTop: 14 }}>
        <h3>IAM Events</h3>
        {!iamEvents.length && <div className="page-sub">No IAM events yet.</div>}
        {!!iamEvents.length && (
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Event</th>
                <th>IP</th>
                <th>Success</th>
              </tr>
            </thead>
            <tbody>
              {iamEvents.map(e => (
                <tr key={e.id}>
                  <td>{e.time}</td>
                  <td>{e.actor}</td>
                  <td>{e.event_type}</td>
                  <td>{e.source_ip}</td>
                  <td>{e.success ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>ABAC Deny Reasons (24h)</h3>
        <div className="page-sub">Grouped by tenant, resource sensitivity, and deny reason. Auto-refreshes every 15s.</div>
        <div className="list" style={{ marginTop: 10 }}>
          <div className="list-item">
            <div>Total denied requests</div>
            <strong>{abacTotal}</strong>
          </div>
        </div>
        {abacLoading && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
        {abacError && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>Error: {abacError}</div>}
        {!abacLoading && !abacError && !abacGroups.length && (
          <div className="page-sub" style={{ marginTop: 10 }}>No ABAC denies in the selected window.</div>
        )}
        {!!abacGroups.length && (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Sensitivity</th>
                <th>Reason</th>
                <th>Count</th>
                <th>Latest</th>
                <th>Drilldown</th>
              </tr>
            </thead>
            <tbody>
              {abacGroups.map((row) => (
                <tr key={`${row.tenant_id}|${row.resource_sensitivity}|${row.abac_reason}`}>
                  <td>{row.tenant_id}</td>
                  <td>{row.resource_sensitivity}</td>
                  <td>{row.abac_reason}</td>
                  <td>{row.count}</td>
                  <td>{row.latest_created_at ? new Date(row.latest_created_at).toLocaleString() : '-'}</td>
                  <td>
                    {row.sample_trace_id ? (
                      <a
                        className="btn ghost"
                        style={{ padding: '4px 8px', borderRadius: 10 }}
                        href={`/api/v1/admin/security/drilldown/${encodeURIComponent(row.sample_trace_id)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open
                      </a>
                    ) : (
                      <span className="page-sub">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Attack Trends (24h)</h3>
          <div className="page-sub">By security type/threat/vector. Time-bucketed from security telemetry.</div>
          {attackLoading && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
          {attackError && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>Error: {attackError}</div>}
          {!attackLoading && !attackError && !attackTotals.length && (
            <div className="page-sub" style={{ marginTop: 10 }}>No attack trend data in window.</div>
          )}
          {!!attackTotals.length && (
            <div className="list" style={{ marginTop: 10 }}>
              {attackTotals.map((r) => (
                <div className="list-item" key={r.security_type}>
                  <div>{r.security_type}</div>
                  <strong>{r.count}</strong>
                </div>
              ))}
            </div>
          )}
          {!!attackRecentBuckets.length && (
            <table className="table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Hour</th>
                  <th>Type</th>
                  <th>Vector</th>
                  <th>Count</th>
                </tr>
              </thead>
              <tbody>
                {attackRecentBuckets.map((b, idx) => (
                  <tr key={`${b.hour}|${b.security_type}|${b.vector}|${idx}`}>
                    <td>{b.hour}</td>
                    <td>{b.security_type}</td>
                    <td>{b.vector}</td>
                    <td>{b.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>ASN/GeoIP Confidence (24h)</h3>
          <div className="page-sub">Downweights VPN/proxy/hosting signals; combines ASN risk, IP churn, and sender/tool behavior.</div>
          {geoLoading && <div className="page-sub" style={{ marginTop: 10 }}>Loading...</div>}
          {geoError && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>Error: {geoError}</div>}
          {!geoLoading && !geoError && !geoTrends.length && (
            <div className="page-sub" style={{ marginTop: 10 }}>No ASN/Geo trend data in window.</div>
          )}
          {!!geoTrends.length && (
            <table className="table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>ASN/Country</th>
                  <th>Events</th>
                  <th>Net Conf</th>
                  <th>Geo Trust</th>
                  <th>Mask Hits</th>
                </tr>
              </thead>
              <tbody>
                {geoTrends.map((g) => (
                  <tr key={`${g.asn}|${g.country}`}>
                    <td>{g.asn} / {g.country}</td>
                    <td>{g.count}</td>
                    <td>{g.network_confidence}</td>
                    <td>{g.geo_trust_level}</td>
                    <td>{g.vpn_or_hosting_hits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Security Events</h3>
        {loading && <div className="page-sub">Loading...</div>}
        {error && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {error}</div>}
        {!events.length && !loading && <div className="page-sub">No events found.</div>}
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Severity</th>
              <th>Technique</th>
              <th>Action</th>
              <th>User</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {events.map(e => (
              <tr key={e.id}>
                <td>{e.time}</td>
                <td>{e.severity}</td>
                <td style={{ maxWidth: 220 }}>{e.technique}</td>
                <td>{e.action}</td>
                <td>{e.user}</td>
                <td><button className="btn secondary" onClick={() => setSelected(e)}>View</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Email Security Incidents</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={emailIncImportantOnly} onChange={(e) => setEmailIncImportantOnly(e.target.checked)} />
            <span className="page-sub">Only Important (warning+error)</span>
          </label>
          <select className="modal-input" value={emailIncSeverity} onChange={(e) => setEmailIncSeverity(e.target.value)} disabled={emailIncImportantOnly}>
            <option value="all">All severities</option>
            <option value="error">error</option>
            <option value="warning">warning</option>
            <option value="info">info</option>
          </select>
          <button className="btn secondary" onClick={async () => {
            setEmailIncLoading(true);
            try {
              if (emailIncImportantOnly) {
                const [warnRows, errRows] = await Promise.all([
                  fetchEmailSecurityIncidents({ severity: 'warning', limit: 50 }),
                  fetchEmailSecurityIncidents({ severity: 'error', limit: 50 }),
                ]);
                const map = new Map<string, EmailSecurityIncident>();
                [...warnRows, ...errRows].forEach(r => map.set(r.id, r));
                const merged = Array.from(map.values()).sort((a, b) => (new Date(b.created_at||'').getTime()) - (new Date(a.created_at||'').getTime()));
                setEmailIncidents(merged.slice(0, 50));
              } else {
                const rows = await fetchEmailSecurityIncidents({ severity: emailIncSeverity === 'all' ? undefined : emailIncSeverity, limit: 50 });
                setEmailIncidents(rows);
              }
            } catch (e: any) {
              setEmailIncError(e.message || 'Reload failed');
            } finally {
              setEmailIncLoading(false);
            }
          }}>Refresh</button>
        </div>
        {emailIncLoading && <div className="page-sub">Loading...</div>}
        {emailIncError && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {emailIncError}</div>}
        {!emailIncidents.length && !emailIncLoading && <div className="page-sub">No incidents found.</div>}
        {!!emailIncidents.length && (
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Severity</th>
                <th>Playbook</th>
                <th>Tags</th>
                <th>Reasons</th>
                <th>View</th>
              </tr>
            </thead>
            <tbody>
              {emailIncidents.map(inc => (
                <tr key={inc.id}>
                  <td>{inc.created_at ? new Date(inc.created_at).toLocaleString() : '-'}</td>
                  <td>{inc.severity}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span>{inc.playbook?.title || inc.playbook?.id || '-'}</span>
                      {!!(inc.playbook?.id) && <span className="badge" title="Playbook ID">{inc.playbook.id}</span>}
                    </div>
                  </td>
                  <td style={{ maxWidth: 240 }}>{(inc.tags || []).slice(0,4).join(', ')}</td>
                  <td style={{ maxWidth: 280 }}>{(inc.reasons || []).slice(0,2).join(' | ')}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="btn secondary" onClick={async () => {
                        try { const r = await getEmailSecurityIncident(inc.id); setEmailIncSelected(r.incident); } catch (e) { alert('Load failed'); }
                      }}>Details</button>
                      <a className="btn ghost" href="/api/v1/tickets/ui" target="_blank" rel="noreferrer">Tickets</a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {emailIncSelected && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Incident Details</h3>
          <div className="list">
            <div className="list-item"><div>ID</div><strong>{emailIncSelected.id}</strong></div>
            <div className="list-item"><div>Severity</div><strong>{emailIncSelected.severity}</strong></div>
            <div className="list-item"><div>Playbook</div><strong>{emailIncSelected.playbook?.title || emailIncSelected.playbook?.id || '-'}</strong></div>
            <div className="list-item"><div>Tags</div><strong>{(emailIncSelected.tags || []).join(', ') || '-'}</strong></div>
          </div>
          <div style={{ marginTop: 10 }}>
            <strong>Reasons</strong>
            <pre className="panel">{JSON.stringify(emailIncSelected.reasons || [], null, 2)}</pre>
          </div>
          <div style={{ marginTop: 10 }}>
            <strong>Evidence (redacted)</strong>
            <pre className="panel">{JSON.stringify(emailIncSelected.evidence_snapshot || {}, null, 2)}</pre>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn secondary" onClick={() => setEmailIncSelected(null)}>Close</button>
            <a className="btn" href="/api/v1/tickets/ui" target="_blank" rel="noreferrer">Open Tickets</a>
          </div>
        </div>
      )}

      {selected && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3>Event Details</h3>
          <div className="list">
            <div className="list-item"><div>Event</div><strong>{selected.id}</strong></div>
            <div className="list-item"><div>Technique</div><strong>{selected.technique}</strong></div>
            <div className="list-item"><div>Risk Score</div><strong>{selected.risk}</strong></div>
          </div>
          <div style={{ marginTop: 12 }}>
            <strong>Payload</strong>
            <pre className="panel">{JSON.stringify(selected.raw, null, 2)}</pre>
          </div>
          <div style={{ marginTop: 12 }}>
            <strong>Sanitized</strong>
            <pre className="panel">{JSON.stringify(selected.normalized, null, 2)}</pre>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn" onClick={async () => { try { await escalateEvent(selected.id); alert('Escalated'); } catch (e: any) { alert('Error: ' + e.message); } }}>Escalate</button>
            <button className="btn secondary" onClick={async () => { try { await blockEvent(selected.id); alert('Blocked'); } catch (e: any) { alert('Error: ' + e.message); } }}>Block</button>
            <button className="btn ghost" onClick={() => alert('Mark false positive not implemented')}>Mark False Positive</button>
          </div>
        </div>
      )}

      {role === 'owner' && (
        <div className="callout" style={{ marginTop: 12 }}>
          Owner-only: export security audit packages and certify incident handling policies.
        </div>
      )}
    </div>
  );
}
