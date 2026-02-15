import React, { useEffect, useMemo, useState } from 'react';
import {
  bulkLabelEmailSecurityIncidents,
  executeEmailSecurityRunbook,
  fetchEmailSecurityConnectorReliability,
  fetchEmailSecurityConnectorDlq,
  fetchEmailSecurityIncidents,
  fetchEmailSecurityRunbook,
  fetchEmailSecuritySuppliers,
  getEmailSecurityIncident,
  type EmailSecurityIncident,
  type EmailSecuritySupplierBucket,
} from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

function classify(inc: EmailSecurityIncident): string {
  const hay = `${(inc.tags || []).join(' ')} ${(inc.reasons || []).join(' ')}`.toLowerCase();
  const rules: Array<[string, RegExp]> = [
    ['BEC / Finance', /(bec|invoice fraud|payment redirect|wire|bank|finance|payee|payid|iban|swift)/i],
    ['Account Takeover', /(password|reset|account takeover|a\-?to|login|mfa|verify your account)/i],
    ['Ransomware', /(ransom|encrypt|decrypt|locker|double extortion)/i],
    ['Spearphishing', /(spear|phish|credential harvest|oauth|consent|impersonat)/i],
    ['C2 / Beaconing', /(c2|beacon|callback|dns tunn|http beacon)/i],
    ['LOLbins / Living-off-land', /(lolbin|powershell|wscript|mshta|rundll32|regsvr32|certutil)/i],
    ['Supply Chain', /(supplier|vendor|supply chain|bpo|compromise|update)/i],
    ['Malware Attachment', /(macro|iso|lnk|js|vbs|exe|payload|dropper|detonation)/i],
  ];
  for (const [name, re] of rules) {
    if (re.test(hay)) return name;
  }
  return 'Other';
}

export function EmailXdr({ role }: Props) {
  const [severity, setSeverity] = useState<'all' | 'error' | 'warning' | 'info'>('all');
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState<EmailSecurityIncident[]>([]);
  const [selected, setSelected] = useState<EmailSecurityIncident | null>(null);
  const [selectedFull, setSelectedFull] = useState<EmailSecurityIncident | null>(null);
  const [suppliers, setSuppliers] = useState<EmailSecuritySupplierBucket[]>([]);
  const [connRel, setConnRel] = useState<any | null>(null);
  const [dlq, setDlq] = useState<any | null>(null);
  const [runbook, setRunbook] = useState<any | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setActionMsg(null);
    try {
      const [inc, sup, rb, rel, dlqRows] = await Promise.all([
        fetchEmailSecurityIncidents({ severity: severity === 'all' ? undefined : severity, limit: 80, offset: 0 }),
        fetchEmailSecuritySuppliers({ limit: 30 }),
        fetchEmailSecurityRunbook(),
        fetchEmailSecurityConnectorReliability(24),
        fetchEmailSecurityConnectorDlq({ limit: 30, offset: 0 }),
      ]);
      setRows(inc || []);
      setSuppliers(sup || []);
      setRunbook(rb || null);
      setConnRel(rel || null);
      setDlq(dlqRows || null);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [severity]);

  useEffect(() => {
    if (!selected?.id) return;
    setSelectedFull(null);
    getEmailSecurityIncident(selected.id)
      .then((r) => setSelectedFull((r as any).incident || null))
      .catch(() => {});
  }, [selected?.id]);

  const byClass = useMemo(() => {
    const map: Record<string, number> = {};
    for (const r of rows || []) {
      const k = classify(r);
      map[k] = (map[k] || 0) + 1;
    }
    const out = Object.entries(map).sort((a, b) => b[1] - a[1]);
    return out;
  }, [rows]);

  return (
    <div className="stagger">
      <div className="card">
        <h3>Email Security (Mini XDR View)</h3>
        <div className="page-sub">
          Triage console for email incidents and playbook execution. Not a replacement for CrowdStrike/Wazuh/firewalls/CDNs.
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <select className="modal-input" style={{ marginTop: 0, maxWidth: 260 }} value={severity} onChange={(e) => setSeverity(e.target.value as any)}>
            <option value="all">All severities</option>
            <option value="error">error</option>
            <option value="warning">warning</option>
            <option value="info">info</option>
          </select>
          <button className="btn secondary" onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Refresh'}</button>
          <a className="btn ghost" href="/api/v1/admin/email_security/demo/funnel" target="_blank" rel="noreferrer">Demo funnel</a>
          <a className="btn ghost" href="/api/v1/admin/email_security/connectors/reliability?hours=24" target="_blank" rel="noreferrer">Connector reliability JSON</a>
        </div>
        {actionMsg && <div className="callout" style={{ marginTop: 10 }}>{actionMsg}</div>}
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Incident Classes (Heuristic)</h3>
          <div className="page-sub">Based on tags/reasons. This is a UI classifier for triage, not detection logic.</div>
          {!rows.length && !loading && <div className="page-sub" style={{ marginTop: 10 }}>No incidents loaded.</div>}
          {!!byClass.length && (
            <div className="list" style={{ marginTop: 10 }}>
              {byClass.slice(0, 8).map(([k, v]) => (
                <div className="list-item" key={k}><div>{k}</div><strong>{v}</strong></div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3>Connector Reliability (24h)</h3>
          <div className="page-sub">Shows if your Gmail/M365 ingest pipeline is healthy and not dropping events.</div>
          {!connRel && <div className="page-sub" style={{ marginTop: 10 }}>No data.</div>}
          {!!connRel && (
            <pre className="panel" style={{ maxHeight: 240, overflow: 'auto' }}>{JSON.stringify(connRel, null, 2)}</pre>
          )}
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Supplier Buckets</h3>
          <div className="page-sub">Good for spotting high-volume vendors that suddenly go noisy.</div>
          {!suppliers.length && !loading && <div className="page-sub" style={{ marginTop: 10 }}>No suppliers.</div>}
          {!!suppliers.length && (
            <table className="table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Supplier hash</th>
                  <th>Error</th>
                  <th>Warning</th>
                  <th>Info</th>
                </tr>
              </thead>
              <tbody>
                {suppliers.slice(0, 10).map((s) => (
                  <tr key={s.supplier_key_hash}>
                    <td style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{s.supplier_key_hash.slice(0, 10)}…</td>
                    <td>{s.counts?.error || 0}</td>
                    <td>{s.counts?.warning || 0}</td>
                    <td>{s.counts?.info || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>DLQ (Dead Letter Queue)</h3>
          <div className="page-sub">Connector backlog. If this grows, you are missing alerts.</div>
          {!dlq?.items?.length && <div className="page-sub" style={{ marginTop: 10 }}>DLQ empty.</div>}
          {!!dlq?.items?.length && (
            <pre className="panel" style={{ maxHeight: 240, overflow: 'auto' }}>{JSON.stringify((dlq.items || []).slice(0, 10), null, 2)}</pre>
          )}
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Incidents</h3>
          {!rows.length && !loading && <div className="page-sub">No incidents.</div>}
          {!!rows.length && (
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Severity</th>
                  <th>Class</th>
                  <th>Playbook</th>
                  <th>Tags</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 50).map((r) => (
                  <tr key={r.id}>
                    <td>{r.created_at ? new Date(r.created_at).toLocaleString() : '-'}</td>
                    <td>{r.severity}</td>
                    <td>{classify(r)}</td>
                    <td>{r.playbook?.title || r.playbook?.id || '-'}</td>
                    <td style={{ maxWidth: 220 }}>{(r.tags || []).slice(0, 3).join(', ')}</td>
                    <td><button className="btn secondary" onClick={() => setSelected(r)}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>Incident Detail</h3>
          {!selected && <div className="page-sub">Select an incident to inspect evidence and next steps.</div>}
          {!!selected && (
            <>
              <div className="list">
                <div className="list-item"><div>ID</div><strong style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{selected.id}</strong></div>
                <div className="list-item"><div>Severity</div><strong>{selected.severity}</strong></div>
                <div className="list-item"><div>Class</div><strong>{classify(selected)}</strong></div>
                <div className="list-item"><div>Playbook</div><strong>{selected.playbook?.title || selected.playbook?.id || '-'}</strong></div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <button
                  className="btn"
                  onClick={async () => {
                    try {
                      await bulkLabelEmailSecurityIncidents({
                        incident_ids: [selected.id],
                        outcome_type: 'human_verdict',
                        outcome_value: 'escalate_mssp',
                        actor_role: role,
                        note: 'Escalate to MSSP (demo action)',
                      });
                      setActionMsg('Recorded: escalated to MSSP (demo label).');
                    } catch {
                      setActionMsg('Failed to record MSSP escalation.');
                    }
                  }}
                >
                  Escalate to MSSP
                </button>
                <button
                  className="btn secondary"
                  onClick={async () => {
                    try {
                      await bulkLabelEmailSecurityIncidents({
                        incident_ids: [selected.id],
                        outcome_type: 'human_verdict',
                        outcome_value: 'false_positive',
                        actor_role: role,
                        note: 'Mark false positive (demo label)',
                      });
                      setActionMsg('Recorded: false positive (demo label).');
                    } catch {
                      setActionMsg('Failed to record label.');
                    }
                  }}
                >
                  Mark False Positive
                </button>
                <button className="btn ghost" onClick={() => setSelected(null)}>Close</button>
              </div>

              <div style={{ marginTop: 10 }}>
                <div className="page-sub" style={{ fontWeight: 600 }}>Reasons</div>
                <pre className="panel" style={{ maxHeight: 180, overflow: 'auto' }}>{JSON.stringify(selectedFull?.reasons || selected.reasons || [], null, 2)}</pre>
              </div>
              <div style={{ marginTop: 10 }}>
                <div className="page-sub" style={{ fontWeight: 600 }}>Evidence snapshot (redacted)</div>
                <pre className="panel" style={{ maxHeight: 220, overflow: 'auto' }}>{JSON.stringify(selectedFull?.evidence_snapshot || selected.evidence_snapshot || {}, null, 2)}</pre>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Next Steps Runbook</h3>
        <div className="page-sub">Execute prebuilt scenarios to generate live incidents for demos (safe, synthetic).</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          <button
            className="btn secondary"
            onClick={async () => {
              try {
                await executeEmailSecurityRunbook({ scenarios: ['bec_invoice_redirect', 'oauth_consent_phish', 'malware_attachment_macro'] });
                setActionMsg('Runbook executed. Refresh to see new incidents.');
                await load();
              } catch {
                setActionMsg('Runbook execution failed.');
              }
            }}
          >
            Run demo scenarios
          </button>
          <a className="btn ghost" href="/api/v1/admin/email_security/demo/runbook" target="_blank" rel="noreferrer">Open runbook JSON</a>
        </div>
        {runbook && <pre className="panel" style={{ maxHeight: 220, overflow: 'auto', marginTop: 10 }}>{JSON.stringify(runbook, null, 2)}</pre>}
      </div>
    </div>
  );
}

