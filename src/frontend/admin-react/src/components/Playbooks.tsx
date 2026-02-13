import React, { useEffect, useMemo, useState } from 'react';
import {
  dryRunAdminPlaybooks,
  fetchAdminPlaybookDlq,
  fetchAdminPlaybookDiff,
  fetchAdminPlaybookKpis,
  fetchAdminPlaybookReliability,
  fetchAdminPlaybookTrail,
  fetchAdminPlaybooks,
  fetchAdminStreamHealth,
  fetchAdminLlmRouting,
  fetchApprovals,
  fetchTenantConfig,
  putTenantConfig,
  publishAdminPlaybook,
  recoverAdminStreams,
  replayAdminStreams,
  reprocessAdminPlaybookDlq,
  rollbackAdminPlaybook,
  validateAdminPlaybooks,
  type AdminPlaybook,
  type ApprovalItem,
} from '../api';

export function Playbooks() {
  const [playbooks, setPlaybooks] = useState<AdminPlaybook[]>([]);
  const [selected, setSelected] = useState<AdminPlaybook | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [includeDisabled, setIncludeDisabled] = useState(true);

  const [validateResult, setValidateResult] = useState<{ valid: boolean; errors: string[] } | null>(null);
  const [dryTags, setDryTags] = useState('payment_fraud');
  const [dryRiskBand, setDryRiskBand] = useState('high');
  const [dryResult, setDryResult] = useState<any>(null);

  const [updateJson, setUpdateJson] = useState('{\n  "enabled": true\n}');
  const [publishApprovalId, setPublishApprovalId] = useState('');
  const [publishResp, setPublishResp] = useState<any>(null);

  const [rollbackVersion, setRollbackVersion] = useState('');
  const [rollbackApprovalId, setRollbackApprovalId] = useState('');
  const [rollbackResp, setRollbackResp] = useState<any>(null);

  const [diffFrom, setDiffFrom] = useState('');
  const [diffTo, setDiffTo] = useState('');
  const [diffResult, setDiffResult] = useState<{ diff: string[] } | null>(null);

  const [kpiDays, setKpiDays] = useState(30);
  const [kpis, setKpis] = useState<any>(null);
  const [reliability, setReliability] = useState<any>(null);
  const [trail, setTrail] = useState<any>(null);
  const [trailActionFilter, setTrailActionFilter] = useState('');
  const [dlq, setDlq] = useState<any>(null);
  const [streamHealth, setStreamHealth] = useState<any>(null);
  const [llmRouting, setLlmRouting] = useState<any>(null);
  const [llmWindowMinutes, setLlmWindowMinutes] = useState(60);
  const [llmTenantFilter, setLlmTenantFilter] = useState('');
  const [routingTenantId, setRoutingTenantId] = useState('global');
  const [routingPolicyJson, setRoutingPolicyJson] = useState('{\n  "fallback": {\n    "standard": ["openai", "anthropic", "ollama"]\n  }\n}');
  const [opsResult, setOpsResult] = useState<any>(null);
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);

  async function loadPlaybooks() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAdminPlaybooks({ includeDisabled });
      setPlaybooks(res.playbooks || []);
      if (!selected && res.playbooks?.length) {
        setSelected(res.playbooks[0]);
      } else if (selected) {
        const fresh = (res.playbooks || []).find((p) => p.id === selected.id) || null;
        setSelected(fresh);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to load playbooks');
    } finally {
      setLoading(false);
    }
  }

  async function loadApprovals() {
    try {
      const rows = await fetchApprovals();
      setApprovals(rows || []);
    } catch {
      setApprovals([]);
    }
  }

  async function loadKpis(days = kpiDays) {
    try {
      const data = await fetchAdminPlaybookKpis(days);
      setKpis(data || null);
    } catch {
      setKpis(null);
    }
  }

  async function loadReliability(days = kpiDays) {
    try {
      const data = await fetchAdminPlaybookReliability(days);
      setReliability(data || null);
    } catch {
      setReliability(null);
    }
  }

  async function loadTrail(playbookId: string) {
    try {
      const data = await fetchAdminPlaybookTrail(playbookId, 50);
      setTrail(data || null);
    } catch {
      setTrail(null);
    }
  }

  async function loadDlq(limit = 100) {
    try {
      const data = await fetchAdminPlaybookDlq(limit);
      setDlq(data || null);
    } catch {
      setDlq(null);
    }
  }

  async function loadStreamHealth() {
    try {
      const data = await fetchAdminStreamHealth();
      setStreamHealth(data || null);
    } catch {
      setStreamHealth(null);
    }
  }

  async function loadLlmRouting(windowMinutes = llmWindowMinutes) {
    try {
      const tid = llmTenantFilter.trim();
      const data = await fetchAdminLlmRouting(windowMinutes, tid || null);
      setLlmRouting(data || null);
    } catch {
      setLlmRouting(null);
    }
  }

  async function loadRoutingPolicy(tenantId = routingTenantId) {
    try {
      const tid = tenantId && tenantId !== 'global' ? tenantId : undefined;
      const data = await fetchTenantConfig('llm_routing_policy', tid || null);
      setRoutingPolicyJson(JSON.stringify(data?.value || {}, null, 2));
    } catch {
      setRoutingPolicyJson('{\n  "fallback": {\n    "standard": ["openai", "anthropic", "ollama"]\n  }\n}');
    }
  }

  async function saveRoutingPolicy() {
    let parsed: any;
    try {
      parsed = JSON.parse(routingPolicyJson || '{}');
    } catch {
      setOpsResult({ error: 'Invalid JSON in routing policy' });
      return;
    }
    const tid = routingTenantId && routingTenantId !== 'global' ? routingTenantId : undefined;
    const res = await putTenantConfig('llm_routing_policy', parsed, tid || null);
    setOpsResult({ routing_policy_saved: res, tenant_id: tid || 'global' });
  }

  useEffect(() => {
    loadPlaybooks();
    loadApprovals();
    loadKpis();
    loadReliability();
    loadDlq();
    loadStreamHealth();
    loadLlmRouting();
    loadRoutingPolicy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [includeDisabled]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return playbooks;
    return playbooks.filter((p) =>
      [p.id, p.title, p.domain, p.version].filter(Boolean).join(' ').toLowerCase().includes(q)
    );
  }, [playbooks, filter]);

  const publishApprovalCandidates = useMemo(
    () => approvals.filter((a) => a.capability === 'playbook_publish' && a.status === 'pending'),
    [approvals]
  );
  const rollbackApprovalCandidates = useMemo(
    () => approvals.filter((a) => a.capability === 'playbook_rollback' && a.status === 'pending'),
    [approvals]
  );

  return (
    <div className="grid-2" style={{ gridTemplateColumns: '320px 1fr', alignItems: 'start' }}>
      <div className="card">
        <h3>Playbooks</h3>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <input className="modal-input" placeholder="Filter by id/title/domain" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
          <input type="checkbox" checked={includeDisabled} onChange={(e) => setIncludeDisabled(e.target.checked)} />
          <span className="page-sub">Include disabled</span>
        </label>
        <button className="btn secondary" onClick={() => loadPlaybooks()}>Refresh</button>
        {loading && <div className="page-sub" style={{ marginTop: 8 }}>Loading...</div>}
        {error && <div className="page-sub" style={{ marginTop: 8, color: '#9f2d1b' }}>{error}</div>}
        <div className="list" style={{ maxHeight: 560, overflow: 'auto' }}>
          {filtered.map((pb) => (
            <button
              key={pb.id}
              className={`btn ${selected?.id === pb.id ? '' : 'secondary'}`}
              style={{ justifyContent: 'space-between' }}
              onClick={() => {
                setSelected(pb);
                setDiffFrom(pb.version || '');
                setDiffTo(pb.version || '');
                loadTrail(pb.id);
              }}
            >
              <span>{pb.id}</span>
              <span className="badge">{pb.version || '1.0.0'}</span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="card">
          <h3>Selected Playbook</h3>
          {!selected && <div className="page-sub">Select a playbook.</div>}
          {selected && (
            <div className="list">
              <div className="list-item"><div>ID</div><strong>{selected.id}</strong></div>
              <div className="list-item"><div>Title</div><strong>{selected.title || '-'}</strong></div>
              <div className="list-item"><div>Domain</div><strong>{selected.domain || '-'}</strong></div>
              <div className="list-item"><div>Priority</div><strong>{selected.priority ?? '-'}</strong></div>
              <div className="list-item"><div>Version</div><strong>{selected.version || '-'}</strong></div>
              <div className="list-item"><div>Enabled</div><strong>{String(selected.enabled)}</strong></div>
            </div>
          )}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Validate + Dry Run</h3>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              className="btn"
              onClick={async () => {
                const res = await validateAdminPlaybooks();
                setValidateResult(res);
              }}
            >
              Validate Config
            </button>
            {validateResult && <span className="badge">{validateResult.valid ? 'valid' : 'invalid'}</span>}
          </div>
          {validateResult && !validateResult.valid && (
            <pre className="panel">{JSON.stringify(validateResult.errors || [], null, 2)}</pre>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px auto', gap: 8, marginTop: 8 }}>
            <input className="modal-input" value={dryTags} onChange={(e) => setDryTags(e.target.value)} placeholder="tag1,tag2" />
            <select className="modal-input" value={dryRiskBand} onChange={(e) => setDryRiskBand(e.target.value)}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
            <button
              className="btn secondary"
              onClick={async () => {
                const tags = dryTags.split(',').map((x) => x.trim()).filter(Boolean);
                const res = await dryRunAdminPlaybooks({ tags, risk_band: dryRiskBand, context: {} });
                setDryResult(res);
              }}
            >
              Run
            </button>
          </div>
          {dryResult && <pre className="panel">{JSON.stringify(dryResult, null, 2)}</pre>}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Publish Update</h3>
          <div className="page-sub">Requires an approved change request. If omitted, backend will create a pending request.</div>
          <textarea className="modal-input" rows={8} value={updateJson} onChange={(e) => setUpdateJson(e.target.value)} />
          <div style={{ marginTop: 8 }}>
            <select className="modal-input" value={publishApprovalId} onChange={(e) => setPublishApprovalId(e.target.value)}>
              <option value="">No approved ID (create request)</option>
              {publishApprovalCandidates.map((a) => (
                <option key={a.id} value={a.id}>{a.id}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              className="btn"
              disabled={!selected}
              onClick={async () => {
                if (!selected) return;
                let parsed: any = {};
                try {
                  parsed = JSON.parse(updateJson || '{}');
                } catch {
                  setPublishResp({ error: 'Invalid JSON in updates' });
                  return;
                }
                const res = await publishAdminPlaybook({
                  playbook_id: selected.id,
                  updates: parsed,
                  approval_id: publishApprovalId || undefined,
                });
                setPublishResp(res);
                await loadApprovals();
                await loadPlaybooks();
              }}
            >
              Publish
            </button>
            <button className="btn secondary" onClick={() => loadApprovals()}>Refresh Approvals</button>
          </div>
          {publishResp && <pre className="panel">{JSON.stringify(publishResp, null, 2)}</pre>}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Rollback</h3>
          <div className="page-sub">Use a target version and approved rollback request.</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <input className="modal-input" placeholder="target version (e.g. 1.0.0)" value={rollbackVersion} onChange={(e) => setRollbackVersion(e.target.value)} />
            <select className="modal-input" value={rollbackApprovalId} onChange={(e) => setRollbackApprovalId(e.target.value)}>
              <option value="">No approved ID (create request)</option>
              {rollbackApprovalCandidates.map((a) => (
                <option key={a.id} value={a.id}>{a.id}</option>
              ))}
            </select>
          </div>
          <button
            className="btn"
            style={{ marginTop: 8 }}
            disabled={!selected || !rollbackVersion}
            onClick={async () => {
              if (!selected || !rollbackVersion) return;
              const res = await rollbackAdminPlaybook({
                playbook_id: selected.id,
                target_version: rollbackVersion,
                approval_id: rollbackApprovalId || undefined,
              });
              setRollbackResp(res);
              await loadApprovals();
              await loadPlaybooks();
            }}
          >
            Rollback
          </button>
          {rollbackResp && <pre className="panel">{JSON.stringify(rollbackResp, null, 2)}</pre>}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Version Diff</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8 }}>
            <input className="modal-input" placeholder="from version" value={diffFrom} onChange={(e) => setDiffFrom(e.target.value)} />
            <input className="modal-input" placeholder="to version" value={diffTo} onChange={(e) => setDiffTo(e.target.value)} />
            <button
              className="btn secondary"
              disabled={!selected || !diffFrom || !diffTo}
              onClick={async () => {
                if (!selected || !diffFrom || !diffTo) return;
                const res = await fetchAdminPlaybookDiff(selected.id, diffFrom, diffTo);
                setDiffResult(res);
              }}
            >
              Diff
            </button>
          </div>
          {diffResult && (
            <pre className="panel" style={{ maxHeight: 260, overflow: 'auto' }}>
              {(diffResult.diff || []).join('\n')}
            </pre>
          )}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Runtime Ops</h3>
          <div className="page-sub">Redis stream recovery/replay and typed-action DLQ reprocessing.</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            <button className="btn secondary" onClick={() => loadStreamHealth()}>Stream Health</button>
            <button className="btn secondary" onClick={async () => { const res = await recoverAdminStreams(200); setOpsResult(res); await loadStreamHealth(); }}>Recover Pending</button>
            <button className="btn secondary" onClick={async () => { const res = await replayAdminStreams(200); setOpsResult(res); }}>Replay Recent</button>
            <button className="btn secondary" onClick={() => loadDlq(100)}>Load DLQ</button>
            <button className="btn secondary" onClick={async () => { const res = await reprocessAdminPlaybookDlq(100); setOpsResult(res); await loadDlq(100); await loadReliability(kpiDays); }}>Reprocess DLQ</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '140px auto auto', gap: 8, marginBottom: 8 }}>
            <select className="modal-input" value={String(llmWindowMinutes)} onChange={(e) => setLlmWindowMinutes(parseInt(e.target.value, 10) || 60)}>
              <option value="15">15 min</option>
              <option value="60">60 min</option>
              <option value="240">240 min</option>
            </select>
            <button className="btn secondary" onClick={() => loadLlmRouting(llmWindowMinutes)}>LLM Routing</button>
            <input className="modal-input" placeholder="routing policy tenant id or global" value={routingTenantId} onChange={(e) => setRoutingTenantId(e.target.value)} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, marginBottom: 8 }}>
            <input className="modal-input" placeholder="LLM metrics tenant filter (blank=all)" value={llmTenantFilter} onChange={(e) => setLlmTenantFilter(e.target.value)} />
            <button className="btn secondary" onClick={() => loadLlmRouting(llmWindowMinutes)}>Apply Tenant Filter</button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <button className="btn secondary" onClick={() => loadRoutingPolicy(routingTenantId)}>Load Tenant Routing Policy</button>
            <button className="btn secondary" onClick={() => saveRoutingPolicy()}>Save Tenant Routing Policy</button>
          </div>
          <textarea className="modal-input" rows={8} value={routingPolicyJson} onChange={(e) => setRoutingPolicyJson(e.target.value)} />
          {streamHealth && <pre className="panel">{JSON.stringify(streamHealth, null, 2)}</pre>}
          {llmRouting && (
            <>
              <div className="page-sub">
                Window: {llmRouting.window_minutes}m
                {llmRouting.tenant_id ? ` | Tenant: ${llmRouting.tenant_id}` : ' | Tenant: all'}
              </div>
              <div style={{ border: '1px solid #d8dee6', borderRadius: 8, padding: 8, marginBottom: 8 }}>
                {(() => {
                  const series = (llmRouting.series || []) as Array<any>;
                  if (!series.length) return <div className="page-sub">No routing events in selected window.</div>;
                  const w = 420;
                  const h = 110;
                  const pad = 8;
                  const maxY = Math.max(1, ...series.map((s) => Number(s.avg_backoff_ms || 0)));
                  const pts = series
                    .map((s, i) => {
                      const x = pad + (i * (w - pad * 2)) / Math.max(series.length - 1, 1);
                      const y = h - pad - ((Number(s.avg_backoff_ms || 0) / maxY) * (h - pad * 2));
                      return `${x},${y}`;
                    })
                    .join(' ');
                  return (
                    <div>
                      <div className="page-sub" style={{ marginBottom: 4 }}>Avg Backoff Trend (ms)</div>
                      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: h }}>
                        <polyline fill="none" stroke="#2f6fed" strokeWidth="2" points={pts} />
                      </svg>
                    </div>
                  );
                })()}
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Attempts</th>
                    <th>Success</th>
                    <th>Retry Events</th>
                    <th>Avg Backoff (ms)</th>
                    <th>Max Backoff (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {(llmRouting.by_provider || []).map((r: any) => (
                    <tr key={r.provider}>
                      <td>{r.provider}</td>
                      <td>{r.attempts}</td>
                      <td>{r.success}</td>
                      <td>{r.retry_events}</td>
                      <td>{Math.round(r.avg_backoff_ms || 0)}</td>
                      <td>{r.max_backoff_ms || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {opsResult && <pre className="panel">{JSON.stringify(opsResult, null, 2)}</pre>}
          {dlq && <pre className="panel">{JSON.stringify(dlq, null, 2)}</pre>}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>KPIs</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
            <select className="modal-input" value={String(kpiDays)} onChange={(e) => setKpiDays(parseInt(e.target.value, 10) || 30)}>
              <option value="7">7 days</option>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
            </select>
            <button className="btn secondary" onClick={() => loadKpis(kpiDays)}>Refresh</button>
            <button className="btn secondary" onClick={() => loadReliability(kpiDays)}>Reliability</button>
          </div>
          {kpis && (
            <>
              <div className="list">
                <div className="list-item"><div>Total Runs</div><strong>{kpis?.totals?.total_runs ?? 0}</strong></div>
                <div className="list-item"><div>Trigger Precision</div><strong>{kpis?.totals?.trigger_precision ?? '-'}</strong></div>
                <div className="list-item"><div>False Positives</div><strong>{kpis?.totals?.false_positives ?? 0}</strong></div>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Playbook</th>
                    <th>Runs</th>
                    <th>Precision</th>
                    <th>False Positives</th>
                    <th>MTTC (min)</th>
                  </tr>
                </thead>
                <tbody>
                  {(kpis.by_playbook || []).map((r: any) => (
                    <tr key={r.playbook_id}>
                      <td>{r.playbook_id}</td>
                      <td>{r.total_runs}</td>
                      <td>{r.trigger_precision ?? '-'}</td>
                      <td>{r.false_positives ?? 0}</td>
                      <td>{r.mean_time_to_close_min ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Action Reliability</h3>
          {reliability && (
            <>
              <div className="list">
                <div className="list-item"><div>Attempts</div><strong>{reliability?.totals?.attempts ?? 0}</strong></div>
                <div className="list-item"><div>Completed</div><strong>{reliability?.totals?.completed ?? 0}</strong></div>
                <div className="list-item"><div>Failed</div><strong>{reliability?.totals?.failed ?? 0}</strong></div>
                <div className="list-item"><div>DLQ</div><strong>{reliability?.totals?.dlq ?? 0}</strong></div>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Attempts</th>
                    <th>Completion</th>
                    <th>DLQ</th>
                  </tr>
                </thead>
                <tbody>
                  {(reliability.by_action || []).map((r: any) => (
                    <tr key={r.action_type}>
                      <td>{r.action_type}</td>
                      <td>{r.attempts}</td>
                      <td>{r.completion_rate ?? '-'}</td>
                      <td>{r.dlq ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h3 style={{ marginTop: 12 }}>Provider Retry/Backoff</h3>
              <div style={{ border: '1px solid #d8dee6', borderRadius: 8, padding: 8, marginBottom: 8 }}>
                {(() => {
                  const rows = (reliability?.by_provider || []) as Array<any>;
                  if (!rows.length) return <div className="page-sub">No provider metrics available for selected window.</div>;
                  const w = 420;
                  const h = 110;
                  const pad = 8;
                  const maxY = Math.max(1, ...rows.map((r) => Number(r.avg_backoff_ms || 0)));
                  const bars = rows.slice(0, 8).map((r, i) => {
                    const bw = (w - pad * 2) / Math.max(rows.slice(0, 8).length, 1) - 6;
                    const x = pad + i * ((w - pad * 2) / Math.max(rows.slice(0, 8).length, 1)) + 3;
                    const bh = ((Number(r.avg_backoff_ms || 0) / maxY) * (h - pad * 2));
                    const y = h - pad - bh;
                    return { x, y, bw, bh };
                  });
                  return (
                    <div>
                      <div className="page-sub" style={{ marginBottom: 4 }}>Avg Backoff by Provider (ms)</div>
                      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: h }}>
                        {bars.map((b, i) => (
                          <rect key={i} x={b.x} y={b.y} width={Math.max(6, b.bw)} height={Math.max(2, b.bh)} fill="#2f6fed" opacity={0.8} rx={2} />
                        ))}
                      </svg>
                    </div>
                  );
                })()}
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Attempts</th>
                    <th>Completed</th>
                    <th>Failed</th>
                    <th>Retry Events</th>
                    <th>Avg Backoff (ms)</th>
                    <th>Max Backoff (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {(reliability.by_provider || []).map((r: any) => (
                    <tr key={r.provider}>
                      <td>{r.provider}</td>
                      <td>{r.attempts}</td>
                      <td>{r.completed}</td>
                      <td>{r.failed}</td>
                      <td>{r.retry_events}</td>
                      <td>{Math.round(r.avg_backoff_ms || 0)}</td>
                      <td>{r.max_backoff_ms || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Immutable Trail</h3>
          <div className="page-sub">Publish/rollback evidence with hash chain roots.</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, marginTop: 8, marginBottom: 8 }}>
            <input className="modal-input" placeholder="Filter action (publish/rollback)" value={trailActionFilter} onChange={(e) => setTrailActionFilter(e.target.value)} />
            <button className="btn secondary" onClick={() => setTrailActionFilter('')}>Clear</button>
          </div>
          {!selected && <div className="page-sub">Select a playbook to load trail.</div>}
          {selected && <button className="btn secondary" onClick={() => loadTrail(selected.id)}>Refresh Trail</button>}
          {trail && (
            <table className="table" style={{ marginTop: 8 }}>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Actor</th>
                  <th>Approval</th>
                  <th>Timestamp</th>
                  <th>Payload Hash</th>
                  <th>Prev Hash</th>
                  <th>Merkle Root</th>
                </tr>
              </thead>
              <tbody>
                {(trail.rows || []).filter((r: any) => {
                  const f = trailActionFilter.trim().toLowerCase();
                  if (!f) return true;
                  return String(r.action || '').toLowerCase().includes(f);
                }).map((r: any) => (
                  <tr key={r.id}>
                    <td>{r.action}</td>
                    <td>{r.actor}</td>
                    <td>{r?.metadata?.approval_id || '-'}</td>
                    <td>{r.created_at}</td>
                    <td>{r?.chain?.payload_hash || '-'}</td>
                    <td>{r?.chain?.prev_hash || '-'}</td>
                    <td>{r?.chain?.merkle_root || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
