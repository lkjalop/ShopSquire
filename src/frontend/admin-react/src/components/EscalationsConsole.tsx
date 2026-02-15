import React, { useEffect, useMemo, useRef, useState } from 'react';
import { fetchIncidents, getIncident, issueIncidentStaffToken, updateIncidentStatus } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

type ChatRec = { incident_id?: string; role?: string; message?: string; ts?: number; meta?: any };

function safeJson(v: any) {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function formatTsMs(ms?: number) {
  if (!ms) return '-';
  try {
    return new Date(ms).toLocaleString();
  } catch {
    return String(ms);
  }
}

export function EscalationsConsole({ role }: Props) {
  const [status, setStatus] = useState<'all' | 'open' | 'review' | 'triaged' | 'resolved'>('open');
  const [severity, setSeverity] = useState<'all' | 'critical' | 'high' | 'warn' | 'info'>('all');
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<any | null>(null);
  const [staffToken, setStaffToken] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatRec[]>([]);
  const [chatErr, setChatErr] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  const esRef = useRef<EventSource | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const inc = await fetchIncidents({
        limit: 80,
        offset: 0,
        status: status === 'all' ? undefined : status,
        severity: severity === 'all' ? undefined : severity,
      });
      setRows(Array.isArray(inc) ? inc : []);
    } catch (e: any) {
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 12000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, severity]);

  const connectRoom = async (incidentId: string) => {
    setChat([]);
    setChatErr(null);
    setStaffToken(null);
    try {
      const tok = await issueIncidentStaffToken(incidentId);
      setStaffToken(tok.staff_token);
      if (esRef.current) {
        try { esRef.current.close(); } catch {}
      }
      const url = `${window.location.origin}/api/v1/incidents/${encodeURIComponent(incidentId)}/room/stream?token=${encodeURIComponent(tok.staff_token)}`;
      const es = new EventSource(url);
      esRef.current = es;
      es.onmessage = (ev) => {
        try {
          const arr = JSON.parse(ev.data || '[]');
          if (!Array.isArray(arr)) return;
          setChat((prev) => {
            const next = [...prev];
            for (const rec of arr) next.push(rec);
            return next.slice(-400);
          });
        } catch {}
      };
      es.onerror = () => {
        // browser auto-reconnects; avoid spamming errors
      };
    } catch (e: any) {
      setChatErr('Unable to connect to incident room.');
    }
  };

  useEffect(() => {
    if (!selected?.id) return;
    let cancelled = false;
    setSelectedDetail(null);
    getIncident(selected.id)
      .then((d) => {
        if (!cancelled) setSelectedDetail(d);
      })
      .catch(() => {})
      .finally(() => {});
    connectRoom(selected.id);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  useEffect(() => {
    try {
      if (endRef.current) endRef.current.scrollIntoView({ behavior: 'smooth' });
    } catch {}
  }, [chat.length]);

  const send = async () => {
    const text = (msg || '').trim();
    if (!text || !selected?.id || !staffToken) return;
    setMsg('');
    setChatErr(null);
    try {
      const r = await fetch(`/api/v1/incidents/${encodeURIComponent(selected.id)}/room/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-incident-token': staffToken },
        body: JSON.stringify({ message: text }),
      });
      if (!r.ok) throw new Error('send_failed');
    } catch {
      setChatErr('Send failed.');
    }
  };

  const sidebar = (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{ padding: 14, borderBottom: '1px solid var(--border)' }}>
        <h3 style={{ marginBottom: 8 }}>Escalations</h3>
        <div className="page-sub">Live incidents that need human review.</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <select className="modal-input" style={{ marginTop: 0 }} value={status} onChange={(e) => setStatus(e.target.value as any)}>
            <option value="all">All status</option>
            <option value="open">open</option>
            <option value="review">review</option>
            <option value="triaged">triaged</option>
            <option value="resolved">resolved</option>
          </select>
          <select className="modal-input" style={{ marginTop: 0 }} value={severity} onChange={(e) => setSeverity(e.target.value as any)}>
            <option value="all">All severity</option>
            <option value="critical">critical</option>
            <option value="high">high</option>
            <option value="warn">warn</option>
            <option value="info">info</option>
          </select>
          <button className="btn secondary" onClick={load}>Refresh</button>
        </div>
      </div>
      <div style={{ maxHeight: '64vh', overflowY: 'auto', padding: 10 }}>
        {loading && <div className="page-sub">Loading…</div>}
        {!loading && !rows.length && <div className="page-sub">No incidents.</div>}
        {rows.map((r) => (
          <button
            key={r.id}
            className={`list-item ${selected?.id === r.id ? 'active' : ''}`}
            style={{ width: '100%', cursor: 'pointer', textAlign: 'left' }}
            onClick={() => setSelected(r)}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.title || 'Incident'}
              </div>
              <div className="page-sub" style={{ marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.severity || '-'} · {r.status || '-'}
              </div>
            </div>
            <span className="badge">{String(r.id || '').slice(0, 6)}</span>
          </button>
        ))}
      </div>
    </div>
  );

  const room = (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', minHeight: 520 }}>
      <h3>Incident Room</h3>
      {!selected?.id && <div className="page-sub">Select an incident from the left.</div>}
      {!!selected?.id && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 6 }}>
            <div className="page-sub">
              Incident <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{selected.id}</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {['open', 'triaged', 'resolved'].map((s) => (
                <button
                  key={s}
                  className="btn secondary"
                  onClick={async () => {
                    try {
                      await updateIncidentStatus(selected.id, s);
                      await load();
                      setSelected((prev: any) => ({ ...(prev || {}), status: s }));
                    } catch {}
                  }}
                >
                  Mark {s}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: 12, marginTop: 10, flex: 1, minHeight: 0 }}>
            <div style={{ border: '1px solid var(--border)', borderRadius: 14, background: '#fff', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: 10, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>Chat</div>
                <span className="badge">{staffToken ? 'Connected' : 'Connecting…'}</span>
              </div>
              <div style={{ padding: 10, overflowY: 'auto', flex: 1, background: '#f9fafb' }}>
                {chat.map((c, idx) => {
                  const isStaff = c.role && c.role !== 'buyer' && c.role !== 'assistant';
                  const align = isStaff ? 'flex-end' : 'flex-start';
                  const bg = isStaff ? '#111827' : '#fff';
                  const fg = isStaff ? '#fff' : '#111827';
                  return (
                    <div key={`${idx}`} style={{ display: 'flex', justifyContent: align, marginBottom: 8 }}>
                      <div style={{ maxWidth: '86%', padding: '10px 12px', borderRadius: 12, border: '1px solid #e5e7eb', background: bg, color: fg }}>
                        <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 4 }}>
                          {c.role || 'system'} · {formatTsMs(c.ts)}
                        </div>
                        <div style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{String(c.message || '')}</div>
                      </div>
                    </div>
                  );
                })}
                <div ref={endRef} />
              </div>
              <div style={{ padding: 10, borderTop: '1px solid var(--border)', display: 'flex', gap: 8 }}>
                <input
                  className="modal-input"
                  style={{ marginTop: 0, flex: 1 }}
                  value={msg}
                  placeholder="Reply to buyer…"
                  onChange={(e) => setMsg(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') send(); }}
                />
                <button className="btn" onClick={send} disabled={!msg.trim() || !staffToken}>Send</button>
              </div>
              {chatErr && <div className="page-sub" style={{ padding: 10, color: '#9f2d1b' }}>{chatErr}</div>}
            </div>

            <div style={{ border: '1px solid var(--border)', borderRadius: 14, background: '#fff', overflow: 'hidden' }}>
              <div style={{ padding: 10, borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 13 }}>Context</div>
              <div style={{ padding: 10 }}>
                <div className="page-sub">Severity: <strong>{selected.severity || '-'}</strong></div>
                <div className="page-sub">Status: <strong>{selected.status || '-'}</strong></div>
                <div className="page-sub">Created: <strong>{selected.created_at || '-'}</strong></div>
                <div className="page-sub" style={{ marginTop: 10, fontWeight: 600 }}>Description (redacted)</div>
                <pre className="panel" style={{ maxHeight: 240, overflow: 'auto' }}>{safeJson(selectedDetail?.description || selected.description || {})}</pre>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <a className="btn ghost" href={`/api/v1/admin/incidents/${encodeURIComponent(selected.id)}`} target="_blank" rel="noreferrer">Incident JSON</a>
                  <a className="btn ghost" href={`/api/v1/admin/security/events?limit=50&offset=0`} target="_blank" rel="noreferrer">Security events</a>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );

  return (
    <div className="stagger">
      <div className="grid-2">
        {sidebar}
        {room}
      </div>
      <div className="callout" style={{ marginTop: 14 }}>
        This console is a lightweight escalation room for agent-driven commerce. It does not replace a full SOC console or XDR.
      </div>
    </div>
  );
}

