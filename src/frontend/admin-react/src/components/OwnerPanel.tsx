import React, { useEffect, useState } from 'react';
import { addApiKey, deleteApiKey, listApiKeyAudit, listApiKeys, rotateApiKey, revokeApiKey } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

export function OwnerPanel({ role }: Props) {
  const isOwner = role === 'owner';
  const [keysByRole, setKeysByRole] = useState<Record<string, string[]>>({});
  const [newRole, setNewRole] = useState('merchant');
  const [newKey, setNewKey] = useState('');
  const [audit, setAudit] = useState<any[]>([]);
  const [auditQuery, setAuditQuery] = useState('');
  const [auditAction, setAuditAction] = useState('');
  const [auditRole, setAuditRole] = useState('');
  const [auditSince, setAuditSince] = useState('');
  const [auditUntil, setAuditUntil] = useState('');
  const [status, setStatus] = useState('');

  const refresh = () => {
    if (!isOwner) return;
    listApiKeys().then((d) => setKeysByRole(d.keys || {})).catch(() => {});
    listApiKeyAudit({
      action: auditAction || undefined,
      role: auditRole || undefined,
      since: auditSince ? Math.floor(new Date(auditSince).getTime() / 1000) : undefined,
      until: auditUntil ? Math.floor(new Date(auditUntil).getTime() / 1000) : undefined,
    }).then((d) => setAudit(d.events || [])).catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, [isOwner, auditAction, auditRole, auditSince, auditUntil]);

  return (
    <div className="stagger">
      <div className={`grid-2 ${!isOwner ? 'locked' : ''}`}>
        <div className="card">
          <h3>Billing & Usage</h3>
          <div className="metric">$8,420</div>
          <div className="badge">Current month</div>
          <div className="list">
            <div className="list-item"><div>LLM spend</div><strong>$5,210</strong></div>
            <div className="list-item"><div>Infrastructure</div><strong>$2,340</strong></div>
            <div className="list-item"><div>Support</div><strong>$870</strong></div>
          </div>
        </div>
        <div className="card">
          <h3>Organization Controls</h3>
          <div className="list">
            <div className="list-item"><div>Team seats</div><strong>12</strong></div>
            <div className="list-item"><div>Approval policy</div><strong>Strict</strong></div>
            <div className="list-item"><div>Data retention</div><strong>90 days</strong></div>
          </div>
          <div style={{ marginTop: 10 }}>
            <button className="btn">Open Governance</button>
            <button className="btn secondary" style={{ marginLeft: 8 }}>Export Audit</button>
          </div>
        </div>
        {!isOwner && <div className="lock-overlay">Owner access required</div>}
      </div>

      <div className={`card ${!isOwner ? 'locked' : ''}`} style={{ marginTop: 14 }}>
        <h3>API Key Vault</h3>
        {!isOwner && <div className="lock-overlay">Owner access required</div>}
        {isOwner && (
          <>
            <div className="list">
              {Object.keys(keysByRole).length === 0 && <div className="page-sub">No keys stored yet.</div>}
              {Object.entries(keysByRole).map(([roleName, keys]) => (
                <div key={roleName} className="list-item" style={{ alignItems: 'flex-start' }}>
                  <div>
                    <strong style={{ textTransform: 'capitalize' }}>{roleName}</strong>
                    <div className="page-sub">{keys.join(', ') || 'No keys'}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      className="btn ghost"
                      onClick={() => {
                        const key = prompt(`Remove key from ${roleName}: enter exact value`);
                        if (!key) return;
                        revokeApiKey(roleName, key).then(() => refresh()).catch(() => setStatus('Revoke failed.'));
                      }}
                    >
                      Revoke
                    </button>
                    <button
                      className="btn"
                      onClick={() => {
                        rotateApiKey(roleName).then((res) => {
                          refresh();
                          alert(`New key: ${res.key}`);
                        }).catch(() => setStatus('Rotate failed.'));
                      }}
                    >
                      Rotate
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="page-sub">Add key</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <select className="role-select" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
                  <option value="merchant">Merchant</option>
                  <option value="owner">Owner</option>
                  <option value="developer">Developer</option>
                </select>
                <input
                  className="modal-input"
                  placeholder="new api key"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                />
                <button
                  className="btn"
                  onClick={() => {
                    if (!newKey.trim()) return;
                    addApiKey(newRole, newKey.trim())
                      .then(() => {
                        setNewKey('');
                        refresh();
                      })
                      .catch(() => setStatus('Add failed.'));
                  }}
                >
                  Add
                </button>
              </div>
              {status && <div className="page-sub" style={{ marginTop: 8 }}>{status}</div>}
            </div>
          </>
        )}
      </div>

      <div className={`card ${!isOwner ? 'locked' : ''}`} style={{ marginTop: 14 }}>
        <h3>Key Audit Log</h3>
        {!isOwner && <div className="lock-overlay">Owner access required</div>}
        {isOwner && (
          <>
            <div className="page-sub">Search by action, role, or key mask</div>
            <input
              className="modal-input"
              placeholder="Filter audit events"
              value={auditQuery}
              onChange={(e) => setAuditQuery(e.target.value)}
              style={{ marginTop: 8 }}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              <select className="role-select" value={auditAction} onChange={(e) => setAuditAction(e.target.value)}>
                <option value="">All actions</option>
                <option value="add">add</option>
                <option value="delete">delete</option>
                <option value="rotate">rotate</option>
              </select>
              <select className="role-select" value={auditRole} onChange={(e) => setAuditRole(e.target.value)}>
                <option value="">All roles</option>
                <option value="merchant">merchant</option>
                <option value="owner">owner</option>
                <option value="developer">developer</option>
              </select>
              <input
                className="modal-input"
                type="date"
                value={auditSince}
                onChange={(e) => setAuditSince(e.target.value)}
              />
              <input
                className="modal-input"
                type="date"
                value={auditUntil}
                onChange={(e) => setAuditUntil(e.target.value)}
              />
              <button className="btn secondary" onClick={refresh}>Apply</button>
            </div>
            <div className="list" style={{ marginTop: 10 }}>
              {audit.length === 0 && <div className="page-sub">No audit events yet.</div>}
              {audit
                .filter((evt) => {
                  const hay = `${evt.action} ${evt.target_role} ${evt.key_mask}`.toLowerCase();
                  return hay.includes(auditQuery.toLowerCase());
                })
                .map((evt, idx) => (
                  <div key={`${evt.ts}-${idx}`} className="list-item">
                    <div>{evt.action} {evt.target_role} key {evt.key_mask}</div>
                    <span className="badge">{new Date((evt.ts || 0) * 1000).toLocaleString()}</span>
                  </div>
                ))}
            </div>
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Compliance Pack</h3>
        <div className="list">
          <div className="list-item"><div>ISO 42001 status</div><span className="badge">Ready</span></div>
          <div className="list-item"><div>EU AI Act logs</div><span className="badge">Complete</span></div>
          <div className="list-item"><div>NIST AI RMF</div><span className="badge">Mapped</span></div>
        </div>
      </div>
    </div>
  );
}
