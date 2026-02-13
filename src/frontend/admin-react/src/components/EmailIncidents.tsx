import React, { useEffect, useMemo, useState } from 'react';
import {
  bulkLabelEmailSecurityIncidents,
  executeEmailSecurityRunbook,
  fetchEmailSecurityIncidents,
  fetchEmailSecurityConnectorDlq,
  fetchEmailSecurityConnectorReliability,
  fetchEmailSecurityFeedbackSummary,
  fetchEmailSecurityRunbook,
  fetchEmailSecuritySuppliers,
  fetchPlaybookById,
  getEmailSecurityIncident,
  requeueEmailSecurityConnectorDlq,
  type EmailSecurityIncident,
  type EmailSecuritySupplierBucket,
  type PlaybookDetails,
} from '../api';

export function EmailIncidents() {
  const [incidents, setIncidents] = useState<EmailSecurityIncident[]>([]);
  const [suppliers, setSuppliers] = useState<EmailSecuritySupplierBucket[]>([]);
  const [supplierKeyHash, setSupplierKeyHash] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [severity, setSeverity] = useState<string>('important');
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(25);
  const [playbookFilter, setPlaybookFilter] = useState('');
  const [ticketsOnly, setTicketsOnly] = useState(false);
  const [selected, setSelected] = useState<EmailSecurityIncident | null>(null);
  const [selectedLoading, setSelectedLoading] = useState(false);
  const [playbook, setPlaybook] = useState<PlaybookDetails | null>(null);
  const [playbookLoading, setPlaybookLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({});
  const [bulkOutcome, setBulkOutcome] = useState('false_positive');
  const [bulkNote, setBulkNote] = useState('');
  const [bulkResult, setBulkResult] = useState<any>(null);
  const [feedbackSummary, setFeedbackSummary] = useState<any>(null);
  const [connectorReliability, setConnectorReliability] = useState<any>(null);
  const [connectorDlq, setConnectorDlq] = useState<any>(null);
  const [runbookGuide, setRunbookGuide] = useState<any>(null);
  const [runbookExec, setRunbookExec] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadSuppliers() {
      try {
        const rows = await fetchEmailSecuritySuppliers({ limit: 50 });
        if (!cancelled) setSuppliers(rows);
      } catch (e) {
        if (!cancelled) setSuppliers([]);
      }
    }
    loadSuppliers();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadOps() {
      try {
        const [guide, fb, rel, dlq] = await Promise.all([
          fetchEmailSecurityRunbook(),
          fetchEmailSecurityFeedbackSummary({ hours: 24 * 30 }),
          fetchEmailSecurityConnectorReliability(24),
          fetchEmailSecurityConnectorDlq({ limit: 50, offset: 0 }),
        ]);
        if (cancelled) return;
        setRunbookGuide(guide || null);
        setFeedbackSummary(fb || null);
        setConnectorReliability(rel || null);
        setConnectorDlq(dlq || null);
      } catch (e) {
        if (!cancelled) {
          setRunbookGuide(null);
          setFeedbackSummary(null);
          setConnectorReliability(null);
          setConnectorDlq(null);
        }
      }
    }
    loadOps();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    async function run() {
      try {
        const serverPlaybookId = playbookFilter && !playbookFilter.trim().includes(' ') ? playbookFilter.trim() : undefined;
        if (severity === 'important') {
          const [warnRows, errRows] = await Promise.all([
            fetchEmailSecurityIncidents({ severity: 'warning', limit, offset: 0, playbookId: serverPlaybookId, hasTicket: ticketsOnly || undefined, supplierKeyHash: supplierKeyHash || undefined }),
            fetchEmailSecurityIncidents({ severity: 'error', limit, offset: 0, playbookId: serverPlaybookId, hasTicket: ticketsOnly || undefined, supplierKeyHash: supplierKeyHash || undefined }),
          ]);
          if (cancelled) return;
          const map = new Map<string, EmailSecurityIncident>();
          [...warnRows, ...errRows].forEach(r => map.set(r.id, r));
          const merged = Array.from(map.values()).sort((a, b) => (new Date(b.created_at||'').getTime()) - (new Date(a.created_at||'').getTime()));
          const start = page * limit;
          setIncidents(merged.slice(start, start + limit));
        } else {
          const rows = await fetchEmailSecurityIncidents({ severity: severity === 'all' ? undefined : severity, limit, offset: page * limit, playbookId: serverPlaybookId, hasTicket: ticketsOnly || undefined, supplierKeyHash: supplierKeyHash || undefined });
          if (cancelled) return;
          setIncidents(rows);
        }
      } catch (e: any) {
        if (!cancelled) setError(e.message || 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [severity, page, limit, playbookFilter, ticketsOnly, supplierKeyHash]);

  useEffect(() => {
    let cancelled = false;
    async function loadSelected() {
      if (!selected?.id) return;
      setSelectedLoading(true);
      try {
        const res = await getEmailSecurityIncident(selected.id);
        if (!cancelled) setSelected(res.incident || null);
      } catch (e) {
        // keep current selection
      } finally {
        if (!cancelled) setSelectedLoading(false);
      }
    }
    loadSelected();
    return () => { cancelled = true; };
  }, [selected?.id]);

  useEffect(() => {
    let cancelled = false;
    async function loadPlaybook() {
      const pbId = selected?.playbook?.id;
      if (!pbId) {
        setPlaybook(null);
        return;
      }
      setPlaybookLoading(true);
      try {
        const res = await fetchPlaybookById(pbId);
        if (!cancelled) setPlaybook(res.playbook || null);
      } catch (e) {
        if (!cancelled) setPlaybook(null);
      } finally {
        if (!cancelled) setPlaybookLoading(false);
      }
    }
    loadPlaybook();
    return () => { cancelled = true; };
  }, [selected?.playbook?.id]);

  const filtered = useMemo(() => {
    return (incidents || []).filter(i => {
      const pb = (i.playbook?.title || i.playbook?.id || '').toLowerCase();
      const ticketOk = !ticketsOnly || Boolean(i.ticket?.id || i.ticket?.created);
      const pbOk = !playbookFilter || pb.includes(playbookFilter.toLowerCase());
      return ticketOk && pbOk;
    });
  }, [incidents, ticketsOnly, playbookFilter]);

  const selectedIncidentIds = useMemo(() => Object.keys(selectedIds).filter((k) => selectedIds[k]), [selectedIds]);

  const supplierLabel = (h?: string | null) => {
    const v = String(h || '');
    if (!v) return 'All suppliers';
    return `Supplier ${v.slice(0, 8)}…`;
  };

  const exportCsv = () => {
    const headers = ['id','created_at','severity','risk_band','playbook','tags','reasons','ticket_id'];
    const lines = [headers.join(',')].concat(
      filtered.map(i => [
        i.id,
        i.created_at || '',
        i.severity,
        i.risk_band || '',
        (i.playbook?.title || i.playbook?.id || ''),
        (i.tags || []).slice(0,4).join('|'),
        (i.reasons || []).slice(0,3).join('|'),
        i.ticket?.id || ''
      ].map(v => String(v).split('"').join('""')).map(v => `"${v}"`).join(','))
    ).join('\n');
    const blob = new Blob([lines], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `email_incidents_${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const toggleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => ({ ...prev, [id]: checked }));
  };

  const toggleSelectAllVisible = (checked: boolean) => {
    const next = { ...selectedIds };
    for (const i of filtered) {
      next[i.id] = checked;
    }
    setSelectedIds(next);
  };

  return (
    <div className="grid-2" style={{ gridTemplateColumns: '280px 1fr', alignItems: 'start' }}>
      <div className="card">
        <h3>Suppliers</h3>
        <div className="page-sub" style={{ marginBottom: 8 }}>Grouped by supplier domain hash.</div>
        <div className="list" style={{ maxHeight: 520, overflow: 'auto' }}>
          <button
            className={`btn ${!supplierKeyHash ? '' : 'secondary'}`}
            style={{ justifyContent: 'space-between' }}
            onClick={() => { setPage(0); setSupplierKeyHash(''); setSelected(null); }}
          >
            <span>All suppliers</span>
            <span className="badge">All</span>
          </button>
          {(suppliers || []).map((s) => (
            <button
              key={s.supplier_key_hash}
              className={`btn ${supplierKeyHash === s.supplier_key_hash ? '' : 'secondary'}`}
              style={{ justifyContent: 'space-between' }}
              onClick={() => { setPage(0); setSupplierKeyHash(s.supplier_key_hash); setSelected(null); }}
              title={`Last seen: ${s.last_seen ? new Date(s.last_seen).toLocaleString() : '-'}`}
            >
              <span className="mono">{s.supplier_key_hash.slice(0, 10)}…</span>
              <span className="badge" title="error/warn/info counts">
                {s.counts.error}/{s.counts.warning}/{s.counts.info}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="card">
          <h3>Email Security Incidents</h3>
          <div className="page-sub" style={{ marginBottom: 8 }}>Scope: {supplierLabel(supplierKeyHash)}</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <select className="modal-input" value={severity} onChange={(e) => { setPage(0); setSeverity(e.target.value); }}>
              <option value="important">Important (warning+error)</option>
              <option value="all">All severities</option>
              <option value="error">error</option>
              <option value="warning">warning</option>
              <option value="info">info</option>
            </select>
            <select className="modal-input" value={String(limit)} onChange={(e) => { setPage(0); setLimit(parseInt(e.target.value, 10) || 25); }}>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
            <input className="modal-input" placeholder="Filter by playbook (id or title)" value={playbookFilter} onChange={(e) => { setPage(0); setPlaybookFilter(e.target.value); }} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={ticketsOnly} onChange={(e) => { setPage(0); setTicketsOnly(e.target.checked); }} />
              <span className="page-sub">Tickets only</span>
            </label>
            <button className="btn secondary" onClick={() => exportCsv()}>Export CSV</button>
            <button className="btn secondary" onClick={() => toggleSelectAllVisible(true)}>Select page</button>
            <button className="btn ghost" onClick={() => toggleSelectAllVisible(false)}>Clear page</button>
            <div className="page-sub">Page {page + 1}</div>
            <button className="btn secondary" onClick={() => setPage(Math.max(0, page - 1))}>Prev</button>
            <button className="btn" onClick={() => setPage(page + 1)}>Next</button>
          </div>
          <div className="card" style={{ marginBottom: 10 }}>
            <h4 style={{ marginTop: 0 }}>Analyst Feedback Loop</h4>
            <div className="page-sub" style={{ marginBottom: 8 }}>
              Label selected incidents in bulk to reduce false positives and improve tuning.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr auto', gap: 8 }}>
              <select className="modal-input" value={bulkOutcome} onChange={(e) => setBulkOutcome(e.target.value)}>
                <option value="false_positive">false_positive</option>
                <option value="true_positive">true_positive</option>
                <option value="incorrect">incorrect</option>
                <option value="effective">effective</option>
              </select>
              <input className="modal-input" value={bulkNote} onChange={(e) => setBulkNote(e.target.value)} placeholder="Optional note (e.g., benign vendor domain)" />
              <button
                className="btn"
                disabled={!selectedIncidentIds.length}
                onClick={async () => {
                  try {
                    const res = await bulkLabelEmailSecurityIncidents({
                      incident_ids: selectedIncidentIds,
                      outcome_type: 'analyst_review',
                      outcome_value: bulkOutcome,
                      actor_id: 'admin-ui',
                      actor_role: 'developer',
                      note: bulkNote || undefined,
                    });
                    setBulkResult(res || null);
                    const [fb] = await Promise.all([
                      fetchEmailSecurityFeedbackSummary({ hours: 24 * 30 }),
                    ]);
                    setFeedbackSummary(fb || null);
                  } catch (e: any) {
                    setBulkResult({ error: e?.message || 'Bulk labeling failed' });
                  }
                }}
              >
                Label {selectedIncidentIds.length}
              </button>
            </div>
            {bulkResult && <pre className="panel" style={{ marginTop: 8 }}>{JSON.stringify(bulkResult, null, 2)}</pre>}
            {feedbackSummary && (
              <div className="list" style={{ marginTop: 8 }}>
                <div className="list-item"><div>Labels</div><strong>{feedbackSummary?.totals?.labels ?? 0}</strong></div>
                <div className="list-item"><div>False positives</div><strong>{feedbackSummary?.totals?.false_positives ?? 0}</strong></div>
                <div className="list-item"><div>FP rate</div><strong>{Math.round((Number(feedbackSummary?.false_positive_rate || 0) * 10000)) / 100}%</strong></div>
              </div>
            )}
          </div>
          {loading && <div className="page-sub">Loading...</div>}
          {error && <div className="page-sub" style={{ color: '#9f2d1b' }}>Error: {error}</div>}
          {!filtered.length && !loading && <div className="page-sub">No incidents</div>}
          {!!filtered.length && (
            <table className="table">
              <thead>
                <tr>
                  <th>Select</th>
                  <th>Time</th>
                  <th>Severity</th>
                  <th>Playbook</th>
                  <th>Tags</th>
                  <th>Reasons</th>
                  <th>Ticket</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(i => (
                  <tr key={i.id} style={{ cursor: 'pointer' }} onClick={() => setSelected(i)}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={Boolean(selectedIds[i.id])}
                        onChange={(e) => toggleSelect(i.id, e.target.checked)}
                      />
                    </td>
                    <td>{i.created_at ? new Date(i.created_at).toLocaleString() : '-'}</td>
                    <td>{i.severity}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span>{i.playbook?.title || i.playbook?.id || '-'}</span>
                        {!!(i.playbook?.id) && <span className="badge" title="Playbook ID">{i.playbook.id}</span>}
                      </div>
                    </td>
                    <td style={{ maxWidth: 260 }}>{(i.tags || []).slice(0,4).join(', ')}</td>
                    <td style={{ maxWidth: 320 }}>{(i.reasons || []).slice(0,2).join(' | ')}</td>
                    <td>{i.ticket?.id ? <a className="btn ghost" href={`/api/v1/tickets/${encodeURIComponent(i.ticket.id)}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Open</a> : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Demo Runbook</h3>
          <div className="page-sub" style={{ marginBottom: 8 }}>
            {'Flow: detection -> route -> decision trace -> SIEM handoff -> ticket.'}
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <button
              className="btn secondary"
              onClick={async () => {
                const g = await fetchEmailSecurityRunbook();
                setRunbookGuide(g || null);
              }}
            >
              Load walkthrough
            </button>
            <button
              className="btn"
              onClick={async () => {
                const out = await executeEmailSecurityRunbook({
                  scenarios: ['bec', 'prompt_injection', 'canary', 'supplier_bank_change', 'ioc_phish', 'supplier_reply_hijack'],
                });
                setRunbookExec(out || null);
                const [rel, dlq] = await Promise.all([
                  fetchEmailSecurityConnectorReliability(24),
                  fetchEmailSecurityConnectorDlq({ limit: 50, offset: 0 }),
                ]);
                setConnectorReliability(rel || null);
                setConnectorDlq(dlq || null);
              }}
            >
              Execute demo pack
            </button>
          </div>
          {runbookGuide && <pre className="panel">{JSON.stringify(runbookGuide, null, 2)}</pre>}
          {runbookExec && <pre className="panel">{JSON.stringify(runbookExec, null, 2)}</pre>}
        </div>

        <div className="card" style={{ marginTop: 14 }}>
          <h3>Connector Reliability</h3>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <button
              className="btn secondary"
              onClick={async () => {
                const rel = await fetchEmailSecurityConnectorReliability(24);
                setConnectorReliability(rel || null);
              }}
            >
              Refresh reliability
            </button>
            <button
              className="btn secondary"
              onClick={async () => {
                const dlq = await fetchEmailSecurityConnectorDlq({ limit: 50, offset: 0 });
                setConnectorDlq(dlq || null);
              }}
            >
              Refresh DLQ
            </button>
          </div>
          {connectorReliability && (
            <div>
              <div className="list">
                <div className="list-item"><div>Attempts</div><strong>{connectorReliability?.totals?.attempts ?? 0}</strong></div>
                <div className="list-item"><div>Sent</div><strong>{connectorReliability?.totals?.sent ?? 0}</strong></div>
                <div className="list-item"><div>Retrying</div><strong>{connectorReliability?.totals?.retrying ?? 0}</strong></div>
                <div className="list-item"><div>DLQ</div><strong>{connectorReliability?.totals?.dlq ?? 0}</strong></div>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>Target</th>
                    <th>Attempts</th>
                    <th>Sent</th>
                    <th>Retrying</th>
                    <th>DLQ</th>
                    <th>Avg Attempts</th>
                    <th>Max Backoff (ms)</th>
                  </tr>
                </thead>
                <tbody>
                  {(connectorReliability?.by_target || []).map((r: any) => (
                    <tr key={String(r.target)}>
                      <td>{r.target}</td>
                      <td>{r.attempts}</td>
                      <td>{r.sent}</td>
                      <td>{r.retrying}</td>
                      <td>{r.dlq}</td>
                      <td>{Math.round(Number(r.avg_attempts || 0) * 100) / 100}</td>
                      <td>{r.max_backoff_ms || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {connectorDlq && (
            <div style={{ marginTop: 10 }}>
              <h4 style={{ margin: 0 }}>DLQ Items</h4>
              <table className="table">
                <thead>
                  <tr>
                    <th>Target</th>
                    <th>Attempts</th>
                    <th>Error</th>
                    <th>Decision</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(connectorDlq?.items || []).map((it: any) => (
                    <tr key={String(it.id)}>
                      <td>{it.target}</td>
                      <td>{it.attempts}/{it.max_attempts}</td>
                      <td style={{ maxWidth: 320 }}>{it.last_error || '-'}</td>
                      <td>{it.decision_id || '-'}</td>
                      <td>
                        <button
                          className="btn secondary"
                          onClick={async () => {
                            await requeueEmailSecurityConnectorDlq(String(it.id));
                            const [rel, dlq] = await Promise.all([
                              fetchEmailSecurityConnectorReliability(24),
                              fetchEmailSecurityConnectorDlq({ limit: 50, offset: 0 }),
                            ]);
                            setConnectorReliability(rel || null);
                            setConnectorDlq(dlq || null);
                          }}
                        >
                          Requeue
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {selected && (
          <div className="card" style={{ marginTop: 14 }}>
            <h3>Incident Timeline (Drilldown)</h3>
            {selectedLoading && <div className="page-sub">Loading details…</div>}
            <div className="list">
              <div className="list-item"><div>ID</div><strong className="mono">{selected.id}</strong></div>
              <div className="list-item"><div>Supplier</div><strong className="mono">{selected.supplier_key_hash || '-'}</strong></div>
              <div className="list-item"><div>Severity</div><strong>{selected.severity}</strong></div>
              <div className="list-item"><div>Playbook</div><strong>{selected.playbook?.title || selected.playbook?.id || '-'}</strong></div>
              <div className="list-item"><div>Tags</div><strong>{(selected.tags || []).slice(0, 10).join(', ') || '-'}</strong></div>
            </div>
            <div style={{ marginTop: 10 }}>
              <strong>Reasons</strong>
              <pre className="panel">{JSON.stringify(selected.reasons || [], null, 2)}</pre>
            </div>
            <div style={{ marginTop: 10 }}>
              <strong>Evidence (redacted)</strong>
              <pre className="panel">{JSON.stringify(selected.evidence_snapshot || {}, null, 2)}</pre>
            </div>

            <div style={{ marginTop: 10 }}>
              <strong>Playbook Instructions</strong>
              {playbookLoading && <div className="page-sub">Loading playbook…</div>}
              {!playbookLoading && !playbook && <div className="page-sub">No playbook details available.</div>}
              {playbook && (
                <div className="grid-2" style={{ marginTop: 8 }}>
                  <div>
                    <div className="page-sub">Checks</div>
                    <ul>
                      {(playbook.checks || []).map((c, idx) => <li key={`chk-${idx}`}>{c}</li>)}
                    </ul>
                  </div>
                  <div>
                    <div className="page-sub">Actions</div>
                    <ul>
                      {(playbook.actions || []).map((a, idx) => <li key={`act-${idx}`}>{a}</li>)}
                    </ul>
                    <div className="page-sub" style={{ marginTop: 8 }}>Owners</div>
                    <div>{(playbook.owners || []).join(', ') || '-'}</div>
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button className="btn secondary" onClick={() => setSelected(null)}>Close</button>
              <a className="btn ghost" href="/api/v1/tickets/ui" target="_blank" rel="noreferrer">Tickets</a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
