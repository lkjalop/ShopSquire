import { useEffect, useRef, useState } from 'react';
import styles from './EscalationRoom.module.css';
import { apiUrl, wsUrl, safeJson } from '../lib/api';

type RoomEvent = {
  id?: string;
  user?: string;
  role?: string;
  message?: string;
  time?: string;
};

export default function EscalationRoom({ incidentId, buyerToken, staffToken, onClose }: { incidentId: string; buyerToken?: string | null; staffToken?: string | null; onClose: () => void }) {
  const [events, setEvents] = useState<RoomEvent[]>([]);
  const [mode, setMode] = useState<'ws' | 'sse' | 'poll'>('poll');
  const [input, setInput] = useState('');
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    let ws: WebSocket | null = null;
    let es: EventSource | null = null;

    const fetchSnapshot = async () => {
      try {
        const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/stream`), {
          headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-owner-key' },
        });
        const j = await safeJson(r);
        if (mounted && j && Array.isArray(j.events)) setEvents(j.events);
      } catch {}
    };

    const connectWS = () => {
      try {
        ws = new WebSocket(wsUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/ws`));
        ws.onopen = () => { if (mounted) setMode('ws'); };
        ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data);
            const incoming = Array.isArray(data) ? data : (Array.isArray(data.events) ? data.events : [data]);
            if (mounted && Array.isArray(incoming)) setEvents((prev) => [...prev, ...incoming]);
          } catch {}
        };
        ws.onerror = () => { try { ws && ws.close(); } catch {}; ws = null; };
      } catch {
        ws = null;
      }
    };

    const connectSSE = async () => {
      try {
        // Prefer public token-based SSE if buyer/staff token is available
        const token = buyerToken || staffToken || null;
        let useToken = token;
        // If no token provided but admin key exists, issue a staff token
        if (!useToken) {
          const key = localStorage.getItem('x-api-key') || 'local-owner-key';
          if (key) {
            try {
              const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/token`), {
                method: 'POST',
                headers: { 'x-api-key': key },
              });
              const j = await safeJson(r);
              if (j && j.staff_token) useToken = String(j.staff_token);
            } catch {}
          }
        }
        if (useToken) {
          const u = new URL(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/stream`), window.location.href);
          u.searchParams.set('token', useToken);
          es = new EventSource(u.toString());
        } else {
          es = new EventSource(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/stream`));
        }
        es.onopen = () => { if (mounted) setMode('sse'); };
        es.onmessage = (ev: MessageEvent) => {
          try {
            const data = JSON.parse((ev as any).data);
            const incoming = Array.isArray(data) ? data : (Array.isArray(data.events) ? data.events : [data]);
            if (mounted && Array.isArray(incoming)) setEvents((prev) => [...prev, ...incoming]);
          } catch {}
        };
        (es as any).onerror = () => { try { es && es.close(); } catch {}; es = null; };
      } catch {
        es = null;
      }
    };

    // If we have tokens, skip admin WS and use public SSE to mirror buyer experience.
    if (!buyerToken && !staffToken) connectWS();
    connectSSE();
    if (!ws && !es) {
      setMode('poll');
      fetchSnapshot();
      const iv = setInterval(fetchSnapshot, 5000);
      return () => { clearInterval(iv); };
    }

    return () => {
      mounted = false;
      try { ws && ws.close(); } catch {}
      try { es && es.close(); } catch {}
    };
  }, [incidentId]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 1e9, behavior: 'smooth' });
  }, [events]);

  const sendMessage = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    try {
      const token = buyerToken || staffToken || null;
      if (token) {
        const u = new URL(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/message`), window.location.href);
        u.searchParams.set('token', token);
        const r = await fetch(u.toString(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg }),
        });
        await safeJson(r);
      } else {
        const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/message`), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': localStorage.getItem('x-api-key') || 'local-owner-key',
          },
          body: JSON.stringify({ message: msg }),
        });
        await safeJson(r);
      }
    } catch {}
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <div className={styles.title}>Escalation Room · {incidentId}</div>
          <div>
            <span style={{ fontSize: 12, opacity: 0.8, marginRight: 8 }}>{mode}</span>
            <button className={styles.closeBtn} onClick={onClose}>Close</button>
          </div>
        </div>
        <div ref={bodyRef} className={styles.body}>
          {events.length === 0 && <div style={{ color: '#6b7280' }}>No messages yet.</div>}
          {events.map((e, i) => (
            <div key={e.id || i} className={styles.msg}>
              <div><strong>{e.user || e.role || 'system'}</strong>: {e.message || ''}</div>
              <div className={styles.meta}>{e.time || ''}</div>
            </div>
          ))}
        </div>
        <div className={styles.footer}>
          <input className={styles.input} placeholder="Type a message…" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && sendMessage()} />
          <button className={styles.sendBtn} onClick={sendMessage}>Send</button>
        </div>
      </div>
    </div>
  );
}
