import { useEffect, useRef, useState } from 'react';
import styles from './EscalationRoom.module.css';
import { apiUrl, wsUrl, safeJson } from '../lib/api';
import { apiFetch, csrfHeaders } from '../lib/csrf';
import { clearIncidentTokenCookie, setIncidentTokenCookie } from '../lib/browserSession';

type RoomEvent = {
  id?: string;
  event_id?: string;
  user?: string;
  role?: string;
  event_type?: string;
  message?: string;
  time?: string;
  ts?: number;
  delivery_status?: 'sent' | 'delivered' | 'read' | string;
  actor?: {
    actor_id?: string;
    actor_type?: string;
    display_name?: string;
    title?: string;
    avatar_url?: string | null;
    identity_source?: string;
  };
  meta?: { message_id?: string; [key: string]: unknown };
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
  embedded = false,
  onClose,
  onResolve,
}: {
  incidentId: string;
  buyerToken?: string | null;
  staffToken?: string | null;
  embedded?: boolean;
  onClose: () => void;
  onResolve?: (incidentId: string) => void;
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
  const [summaryCollapsed, setSummaryCollapsed] = useState(true);
  const [remoteTyping, setRemoteTyping] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [resolving, setResolving] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const typingTimerRef = useRef<number | null>(null);
  const typingSentAtRef = useRef(0);

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

        let descObj: any = null;
        if (j && typeof j.description === 'string') {
          try {
            descObj = JSON.parse(j.description);
          } catch {
            descObj = null;
          }
        } else if (j && typeof j.description === 'object' && j.description !== null) {
          descObj = j.description;
        }
        const reason = String(j?.reason || descObj?.reason || '');
        const traceId = String(
          j?.trace_id ||
          j?.traceId ||
          descObj?.trace_id ||
          descObj?.context?.trace_id ||
          j?.event_id ||
          j?.eventId ||
          '',
        );
        setIncidentSummary({
          id: j?.id || incidentId,
          severity: j?.severity || 'unknown',
          status: j?.status || 'unknown',
          title: j?.title || 'Escalated incident',
          reason,
          traceId,
          createdAt: j?.created_at || j?.createdAt || '',
          createdBy: j?.created_by || j?.createdBy || '',
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
    const fetchStatus = async () => {
      try {
        if (buyerToken || staffToken) {
          const token = buyerToken || staffToken || '';
          setIncidentTokenCookie(incidentId, token);
        const r = await fetch(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/summary/public`), {
          credentials: 'include',
          headers: { 'x-incident-token': token },
          });
          const j = await safeJson(r);
          if (!r.ok) throw new Error(parseError(r.status, j, 'summary_status_failed'));
          const st = String(j?.status || '').toLowerCase();
          if (mounted) setResolved(st === 'resolved' || st === 'closed');
          return;
        }
        const headers: Record<string, string> = {};
        if (OWNER_API_KEY) headers['x-api-key'] = OWNER_API_KEY;
        const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}`), {
          credentials: 'include',
          headers,
        });
        const j = await safeJson(r);
        if (!r.ok) throw new Error(parseError(r.status, j, 'summary_status_failed'));
        const st = String(j?.status || '').toLowerCase();
        if (mounted) setResolved(st === 'resolved' || st === 'closed');
      } catch {
        // best effort
      }
    };
    fetchStatus();
    const timer = window.setInterval(fetchStatus, 7000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [OWNER_API_KEY, incidentId, buyerToken, staffToken]);

  useEffect(() => {
    let mounted = true;
    let ws: WebSocket | null = null;
    let es: EventSource | null = null;
    setConnectionError(null);
    setSendError(null);

    const appendIncoming = (raw: any) => {
      const incoming = Array.isArray(raw) ? raw : (Array.isArray(raw?.events) ? raw.events : [raw]);
      if (!mounted || !Array.isArray(incoming)) return;
      const typingEvents = incoming.filter((e: any) => String(e?.event_type || '').toLowerCase() === 'typing');
      if (typingEvents.length > 0) {
        setRemoteTyping(true);
        if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current);
        typingTimerRef.current = window.setTimeout(() => setRemoteTyping(false), 2400);
      }
      const resolveEvents = incoming.filter((e: any) =>
        ['incident_resolved', 'resolved', 'room_closed'].includes(String(e?.event_type || '').toLowerCase())
      );
      const readEvents = incoming.filter((e: any) => String(e?.event_type || '').toLowerCase() === 'message_read');
      if (readEvents.length > 0) {
        const readIds = new Set(readEvents.map((e: any) => String(e?.meta?.message_id || '')).filter(Boolean));
        setEvents((prev) => prev.map((item) => readIds.has(String(item.event_id || item.id || ''))
          ? { ...item, delivery_status: 'read' }
          : item));
      }
      if (resolveEvents.length > 0 && mounted) {
        setResolved(true);
        onResolve?.(incidentId);
      }
      const messageEvents = incoming.filter((e: any) => {
        const t = String(e?.event_type || 'message').toLowerCase();
        return !['typing', 'message_read'].includes(t) && !['incident_resolved', 'resolved', 'room_closed'].includes(t);
      });
      if (messageEvents.length > 0) {
        setRemoteTyping(false);
        setEvents((prev) => {
          const seen = new Set(prev.map((item) => item.event_id || item.id || `${item.role}:${item.ts}:${item.message}`));
          const unique = messageEvents.filter((item: RoomEvent) => {
            const key = item.event_id || item.id || `${item.role}:${item.ts}:${item.message}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          return [...prev, ...unique];
        });
        const viewerIsBuyer = Boolean(buyerToken && !staffToken);
        for (const item of messageEvents as RoomEvent[]) {
          const role = String(item.role || '').toLowerCase();
          const remote = viewerIsBuyer ? role !== 'buyer' : role === 'buyer';
          const messageId = item.event_id || item.id;
          if (!remote || !messageId || ['human_joined', 'human_left'].includes(String(item.event_type || '').toLowerCase())) continue;
          const activeToken = buyerToken || staffToken || null;
          const path = activeToken
            ? `/api/v1/incidents/${encodeURIComponent(incidentId)}/room/message`
            : `/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/message`;
          const headers: Record<string, string> = { 'Content-Type': 'application/json', ...csrfHeaders() };
          if (activeToken) headers['x-incident-token'] = activeToken;
          else if (OWNER_API_KEY) headers['x-api-key'] = OWNER_API_KEY;
          void fetch(apiUrl(path), {
            method: 'POST', credentials: 'include', headers,
            body: JSON.stringify({ event_type: 'read', message_id: messageId }),
          }).catch(() => undefined);
        }
      }
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
          try { ws && ws.close(); } catch { /* ignore */ }
          ws = null;
          if (!mounted) return;
          setConnectionError('WebSocket disconnected. Reconnecting…');
          window.setTimeout(() => {
            if (!mounted) return;
            setConnectionError(null);
            connectWS();
          }, 3000);
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
              headers: { ...csrfHeaders(), 'x-api-key': key },
            });
            const j = await safeJson(r);
            if (!r.ok) {
              throw new Error(parseError(r.status, j, 'token_issue_failed'));
            }
            if (j && j.staff_token) useToken = String(j.staff_token);
          }
        }

        if (useToken) {
          setIncidentTokenCookie(incidentId, useToken);
          // EventSource cannot attach authorization headers. The incident-bound, expiring token is
          // therefore sent on the supported query parameter as well as stored for same-origin use.
          es = new EventSource(apiUrl(
            `/api/v1/incidents/${encodeURIComponent(incidentId)}/room/stream?token=${encodeURIComponent(useToken)}`,
          ));
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
      clearIncidentTokenCookie(incidentId);
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
  }, [events, remoteTyping]);

  useEffect(() => () => {
    if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current);
  }, []);

  const sendTypingSignal = async () => {
    const now = Date.now();
    if (now - typingSentAtRef.current < 800) return;
    typingSentAtRef.current = now;
    try {
      const token = buyerToken || staffToken || null;
      if (token) {
        setIncidentTokenCookie(incidentId, token);
        await fetch(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/message`), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...csrfHeaders(), 'x-incident-token': token },
          body: JSON.stringify({ event_type: 'typing', role: staffToken ? 'staff' : 'buyer' }),
        });
        return;
      }
      await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/message`), {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...csrfHeaders(),
          ...(OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : {}),
        },
        body: JSON.stringify({ event_type: 'typing', role: 'staff' }),
      });
    } catch {
      // best effort
    }
  };

  const resolveCase = async () => {
    if (resolving || resolved) return;
    setResolving(true);
    setSendError(null);
    try {
      await apiFetch(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/status?status=resolved`, {
        method: 'POST',
        headers: OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : undefined,
      });
      setResolved(true);
      onResolve?.(incidentId);
    } catch (e: any) {
      setSendError(`Resolve failed: ${e?.message || 'unknown_error'}.`);
    } finally {
      setResolving(false);
    }
  };

  const sendMessage = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    setSendError(null);
    try {
      const token = buyerToken || staffToken || null;
      if (token) {
        setIncidentTokenCookie(incidentId, token);
        const r = await fetch(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/message`), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...csrfHeaders(), 'x-incident-token': token },
          body: JSON.stringify({ message: msg, role: staffToken ? 'staff' : 'buyer' }),
        });
        const j = await safeJson(r);
        if (!r.ok) throw new Error(parseError(r.status, j, 'send_failed'));
      } else {
        const r = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/message`), {
          method: 'POST',
          credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...csrfHeaders(),
          ...(OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : {}),
        },
          body: JSON.stringify({ message: msg, role: 'staff' }),
        });
        const j = await safeJson(r);
        if (!r.ok) throw new Error(parseError(r.status, j, 'send_failed'));
      }
    } catch (e: any) {
      setSendError(`Send failed: ${e?.message || 'unknown_error'}.`);
    }
  };

  const roleLabel = (e: RoomEvent): string => {
    if (e.actor?.display_name) return e.actor.display_name;
    const role = String(e.role || '').toLowerCase();
    if (buyerToken && !staffToken) {
      if (role === 'buyer') return '[You]';
      if (role === 'staff' || role === 'merchant' || role === 'owner' || role === 'developer') return '[Support]';
      if (role === 'assistant' || role === 'system') return '[System]';
      return '[Support]';
    }
    if (role === 'staff' || role === 'merchant' || role === 'owner' || role === 'developer') return '[You]';
    if (role === 'buyer') return '[Buyer]';
    if (role === 'assistant' || role === 'system') return '[System]';
    return '[Support]';
  };

  const isOwnMessage = (e: RoomEvent): boolean => {
    const role = String(e.role || '').toLowerCase();
    return buyerToken && !staffToken
      ? role === 'buyer'
      : ['staff', 'merchant', 'owner', 'developer'].includes(role);
  };

  const initials = (e: RoomEvent): string => {
    const value = e.actor?.display_name || roleLabel(e).replace(/[\[\]]/g, '');
    return value.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'SS';
  };

  return (
    <div className={embedded ? styles.embedded : styles.overlay} data-testid="human-conversation">
      <div className={embedded ? styles.embeddedPanel : styles.modal}>
        <div className={styles.header}>
          <div>
            <div className={styles.title}>Human support</div>
            <div className={styles.presenceLine} data-testid="human-presence">
              <span className={styles.presenceDot} /> {events.some((e) => e.actor?.actor_type === 'human_staff') ? 'Support is in this conversation' : 'Waiting for a specialist'}
            </div>
          </div>
          <div>
            {!embedded && <a
              href={`/merchant/app/index.html?tab=escalations&incident_id=${encodeURIComponent(incidentId)}`}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 12, opacity: 0.85, marginRight: 10, color: '#111827' }}
              title="Open in Merchant Admin Console"
            >
              Open admin console
            </a>}
            <span style={{ fontSize: 12, opacity: 0.8, marginRight: 8 }}>{mode}</span>
            {!buyerToken && (
              <button className={styles.resolveBtn} onClick={resolveCase} disabled={resolved || resolving}>
                {resolved ? 'Resolved' : (resolving ? 'Resolving...' : 'Mark resolved')}
              </button>
            )}
            <button className={styles.closeBtn} onClick={onClose}>Close</button>
          </div>
        </div>
        {resolved && (
          <div className={styles.resolvedBanner}>
            Case resolved. This incident is closed for active triage.
          </div>
        )}
        <div className={styles.contentLayout}>
          {!embedded && <aside className={styles.summaryPanel}>
            <button className={styles.summaryToggle} onClick={() => setSummaryCollapsed((v) => !v)}>
              <span className={styles.summaryTitle}>Escalation Summary</span>
              <span>{summaryCollapsed ? 'Expand' : 'Collapse'}</span>
            </button>
            {summaryCollapsed && <div className={styles.summaryHint}>Collapsed</div>}
            {!summaryCollapsed && (
              <>
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
              </>
            )}
          </aside>}
          <div ref={bodyRef} className={styles.body}>
            {events.length === 0 && <div style={{ color: '#6b7280' }}>No messages yet.</div>}
            {events.map((e, i) => {
              const presence = ['human_joined', 'human_left'].includes(String(e.event_type || '').toLowerCase());
              if (presence) return <div key={e.event_id || e.id || i} className={styles.presenceEvent}>{e.message}</div>;
              const own = isOwnMessage(e);
              return (
                <div key={e.event_id || e.id || i} className={`${styles.messageRow} ${own ? styles.ownRow : styles.remoteRow}`}>
                  {!own && (
                    e.actor?.avatar_url
                      ? <img className={styles.avatar} src={e.actor.avatar_url} alt="" />
                      : <span className={styles.avatar} aria-hidden="true">{initials(e)}</span>
                  )}
                  <div className={`${styles.msgBubble} ${own ? styles.ownBubble : styles.remoteBubble}`} data-delivery-status={e.delivery_status || 'unknown'}>
                    <div className={styles.actorLine}>
                      <strong>{own ? 'You' : roleLabel(e)}</strong>
                      {!own && e.actor?.title && <span>{e.actor.title}</span>}
                    </div>
                    <div>{e.message || ''}</div>
                    <div className={styles.meta}>{e.time || ''}{own && e.delivery_status ? ` · ${e.delivery_status}` : ''}</div>
                  </div>
                </div>
              );
            })}
            {remoteTyping && (
              <div className={styles.typingRow}>
                <span className={styles.typingLabel}>{buyerToken && !staffToken ? '[Support]' : '[Buyer]'} typing</span>
                <span className={styles.typingDots}><i>.</i><i>.</i><i>.</i></span>
              </div>
            )}
          </div>
        </div>
        {connectionError && <div style={{ padding: '0 12px 10px', color: '#9f2d1b', fontSize: 12 }}>{connectionError}</div>}
        {sendError && <div style={{ padding: '0 12px 10px', color: '#9f2d1b', fontSize: 12 }}>{sendError}</div>}
        <div className={styles.footer}>
          <input
            className={styles.input}
            placeholder={resolved ? 'This conversation is resolved' : 'Message your specialist...'}
            disabled={resolved}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              if (e.target.value.trim()) void sendTypingSignal();
            }}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
          />
          <button className={styles.sendBtn} onClick={sendMessage} disabled={resolved}>Send</button>
        </div>
      </div>
    </div>
  );
}
