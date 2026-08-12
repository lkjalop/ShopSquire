
import { useEffect, useRef, useState } from 'react';
import styles from './EscalationRoom.module.css';
import { apiUrl, safeJson } from '../lib/api';
import { apiFetch } from '../lib/csrf';
import { type IncidentRoomEvent as RoomEvent, useIncidentConversation } from '../hooks/useIncidentConversation';

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
  const [input, setInput] = useState('');
  const [incidentSummary, setIncidentSummary] = useState<any>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryCollapsed, setSummaryCollapsed] = useState(true);
  const [resolving, setResolving] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const {
    events, mode, connectionError, sendError, remoteTyping, resolved, setResolved,
    sendTyping, sendMessage: sendConversationMessage,
  } = useIncidentConversation({
    incidentId, buyerToken, staffToken, ownerApiKey: OWNER_API_KEY, onResolve,
  });

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
    bodyRef.current?.scrollTo({ top: 1e9, behavior: 'smooth' });
  }, [events, remoteTyping]);

  const sendTypingSignal = () => { void sendTyping(); };

  const resolveCase = async () => {
    if (resolving || resolved) return;
    setResolving(true);
    try {
      await apiFetch(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/status?status=resolved`, {
        method: 'POST',
        headers: OWNER_API_KEY ? { 'x-api-key': OWNER_API_KEY } : undefined,
      });
      setResolved(true);
      onResolve?.(incidentId);
    } catch (e: any) {
      console.error('Resolve failed', e);
    } finally {
      setResolving(false);
    }
  };

  const sendMessage = async () => {
    const msg = input.trim();
    if (!msg) return;
    setInput('');
    try { await sendConversationMessage(msg); } catch { /* rendered by transport hook */ }
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
              const messageKind = String(e.meta?.message_kind || e.event_type || 'advice').replace(/_/g, ' ');
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
                    {!own && <div className={styles.messageKind}>{messageKind}</div>}
                    <div>{e.message || ''}</div>
                    {e.meta?.buyer_confirmation_required && (
                      <div className={styles.confirmationNotice}>Proposal only — review and confirm separately before your cart changes.</div>
                    )}
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
