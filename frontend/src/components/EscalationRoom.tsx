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

function parseError(status: number, body: any, fallback: string) {
  if (body && typeof body === 'object') {
    const detail = (body as any).detail || (body as any).error;
    if (detail) return String(detail);
  }
  return `${fallback} (${status})`;
}

export default function EscalationRoom({
  incidentId,
  buyerToken,
  staffToken,
  onClose,
}: {
  incidentId: string;
  buyerToken?: string | null;
  staffToken?: string | null;
  onClose: () => void;
}) {
  const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
  const OWNER_API_KEY = ((import.meta as any).env?.VITE_OWNER_API_KEY as string | undefined) || API_KEY;
  const [events, setEvents] = useState<RoomEvent[]>([]);
  const [mode, setMode] = useState<'ws' | 'sse' | 'poll'>('poll');
  const [input, setInput] = useState('');
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [incidentSummary, setIncidentSummary] = useState<any>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    setSummaryError(null);
    setIncidentSummary(null);

    const loadSummary = async () => {
      try {
        const headers: Record<string, string> = {};
        if (OWNER_API_KEY) headers['x-api-key'] = OWNER_API_KEY;
        const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}`), {
          credentials: 'include',
          headers,
        });
        const j = await safeJson(r);
        if (!r.ok) {
          throw new Error(parseError(r.status, j, 'incident_summary_failed'));
        }
        if (!mounted) return;

        let reason = '';
        let traceId = '';
        try {
          const desc = j && typeof j.description === 'string' ? JSON.parse(j.description) : null;
          reason = String(desc?.reason || '');
          traceId = String(desc?.trace_id || desc?.context?.trace_id || '');
        } catch {
          reason = '';
          traceId = '';
        }
        setIncidentSummary({
          id: j?.id || incidentId,
          severity: j?.severity || 'unknown',
          status: j?.status || 'unknown',
          title: j?.title || 'Escalated incident',
          reason,
          traceId,
          createdAt: j?.created_at || '',
          createdBy: j?.created_by || '',
        });
      } catch (e: any) {
        if (mounted) {
          setSummaryError(e?.message || 'Unable to load incident summary.');
        }
      }
    };

    loadSummary();
    return () => {
      mounted = false;
    };
  }, [OWNER_API_KEY, incidentId]);

  useEffect(() => {
    let mounted = true;
    let ws: WebSocket | null = null;
    let es: EventSource | null = null;
    setConnectionError(null);
    setSendError(null);

    const appendIncoming = (raw: any) => {
      const incoming = Array.isArray(raw) ? raw : (Array.isArray(raw?.events) ? raw.events : [raw]);
      if (!mounted || !Array.isArray(incoming)) return;
      setEvents((prev) => [...prev, ...incoming]);
    };

    const connectWS = () => {
      try {
        ws = new WebSocket(wsUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/ws`));
        ws.onopen = () => {
          if (!mounted) return;
          setMode('ws');
          setConnectionError(null);
        };
        ws.onmessage = (ev) => {
          try {
            appendIncoming(JSON.parse(ev.data));
          } catch {
            // ignore malformed message
          }
        };
        ws.onerror = () => {
          if (mounted) setConnectionError('WebSocket connection failed. Falling back to SSE.');
          try {
            ws && ws.close();
          } catch {
            // ignore close errors
          }
          ws = null;
        };
      } catch {
        ws = null;
      }
    };

    const connectSSE = async () => {
      try {
        const token = buyerToken || staffToken || null;
        let useToken = token;
        if (!useToken) {
          const key = OWNER_API_KEY || '';
          if (key) {
            const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/token`), {
              method: 'POST',
              credentials: 'include',
              headers: { 'x-api-key': key },
            });
            const j = await safeJson(r);
            if (!r.ok) {
              throw new Error(parseError(r.status, j, 'token_issue_failed'));
            }
            if (j && j.staff_token) useToken = String(j.staff_token);
          }
        }

        if (useToken) {
          const u = new URL(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/stream`), window.location.href);
          u.searchParams.set('token', useToken);
          es = new EventSource(u.toString());
        } else {
          setConnectionError('No incident token available.');
          return;
        }

        es.onopen = () => {
          if (!mounted) return;
          setMode('sse');
          setConnectionError(null);
        };
        es.onmessage = (ev: MessageEvent) => {
          try {
            appendIncoming(JSON.parse((ev as any).data));
          } catch {
            // ignore malformed message
          }
        };
        (es as any).onerror = () => {
          if (mounted) setConnectionError('Incident stream disconnected. Reconnecting...');
        };
      } catch (e: any) {
        if (mounted) {
          setMode('poll');
          setConnectionError(`Room connection failed: ${e?.message || 'unknown_error'}.`);
        }
      }
    };

    if (!buyerToken && !staffToken) connectWS();
    connectSSE();

    return () => {
      mounted = false;
      try {
        ws && ws.close();
      } catch {
        // ignore close errors
      }
      try {
        es && es.close();
      } catch {
        // ignore close errors
      }
    };
  }, [OWNER_API_KEY, incidentId, buyerToken, staffToken]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 1e9, behavior: 'smooth' });
  }, [events]);

  const sendMessage = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    setSendError(null);
    try {
      const token = buyerToken || staffToken || null;
      if (token) {
        const u = new URL(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/message`), window.location.href);
        u.searchParams.set('token', token);
        const r = await fetch(u.toString(), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg }),
        });
        const j = await safeJson(r);
        if (!r.ok) throw new Error(parseError(r.status, j, 'send_failed'));
      } else {
        const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/message`), {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            ...(OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : {}),
          },
          body: JSON.stringify({ message: msg }),
        });
        const j = await safeJson(r);
        if (!r.ok) throw new Error(parseError(r.status, j, 'send_failed'));
      }
    } catch (e: any) {
      setSendError(`Send failed: ${e?.message || 'unknown_error'}.`);
    }
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <div className={styles.title}>Escalation Room - {incidentId}</div>
          <div>
            <a
              href={`/merchant/app/index.html?tab=escalations&incident_id=${encodeURIComponent(incidentId)}`}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 12, opacity: 0.85, marginRight: 10, color: '#111827' }}
              title="Open in Merchant Admin Console"
            >
              Open admin console
            </a>
            <span style={{ fontSize: 12, opacity: 0.8, marginRight: 8 }}>{mode}</span>
            <button className={styles.closeBtn} onClick={onClose}>Close</button>
          </div>
        </div>
        <div className={styles.contentLayout}>
          <aside className={styles.summaryPanel}>
            <div className={styles.summaryTitle}>Escalation Summary</div>
            {!incidentSummary && !summaryError && (
              <div className={styles.summaryValue}>Loading incident context...</div>
            )}
            {summaryError && (
              <div className={styles.summaryError}>{summaryError}</div>
            )}
            {incidentSummary && (
              <>
                <div className={styles.summaryItem}><span className={styles.summaryKey}>Severity</span><span className={styles.summaryValue}>{incidentSummary.severity}</span></div>
                <div className={styles.summaryItem}><span className={styles.summaryKey}>Status</span><span className={styles.summaryValue}>{incidentSummary.status}</span></div>
                <div className={styles.summaryItem}><span className={styles.summaryKey}>Reason</span><span className={styles.summaryValue}>{incidentSummary.reason || 'human_review_requested'}</span></div>
                <div className={styles.summaryItem}><span className={styles.summaryKey}>Trace</span><span className={styles.summaryValue}>{incidentSummary.traceId || 'n/a'}</span></div>
                <div className={styles.summaryItem}><span className={styles.summaryKey}>Created</span><span className={styles.summaryValue}>{incidentSummary.createdAt || 'n/a'}</span></div>
              </>
            )}
          </aside>
          <div ref={bodyRef} className={styles.body}>
            {events.length === 0 && <div style={{ color: '#6b7280' }}>No messages yet.</div>}
            {events.map((e, i) => (
              <div key={e.id || i} className={styles.msg}>
                <div><strong>{e.user || e.role || 'system'}</strong>: {e.message || ''}</div>
                <div className={styles.meta}>{e.time || ''}</div>
              </div>
            ))}
          </div>
        </div>
        {connectionError && <div style={{ padding: '0 12px 10px', color: '#9f2d1b', fontSize: 12 }}>{connectionError}</div>}
        {sendError && <div style={{ padding: '0 12px 10px', color: '#9f2d1b', fontSize: 12 }}>{sendError}</div>}
        <div className={styles.footer}>
          <input
            className={styles.input}
            placeholder="Type a message..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
          />
          <button className={styles.sendBtn} onClick={sendMessage}>Send</button>
        </div>
      </div>
    </div>
  );
}
