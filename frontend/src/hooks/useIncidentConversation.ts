import { useCallback, useEffect, useRef, useState } from 'react';

import { apiUrl, safeJson, wsUrl } from '../lib/api';
import { clearIncidentTokenCookie, setIncidentTokenCookie } from '../lib/browserSession';
import { csrfHeaders } from '../lib/csrf';

export type IncidentActor = {
  actor_id?: string;
  actor_type?: string;
  display_name?: string;
  title?: string;
  avatar_url?: string | null;
  identity_source?: string;
};

export type IncidentRoomEvent = {
  id?: string;
  event_id?: string;
  user?: string;
  role?: string;
  event_type?: string;
  message?: string;
  time?: string;
  ts?: number;
  delivery_status?: 'sent' | 'delivered' | 'read' | string;
  actor?: IncidentActor;
  meta?: { message_id?: string; message_kind?: string; buyer_confirmation_required?: boolean; [key: string]: unknown };
};

type Mode = 'ws' | 'sse' | 'poll';

function eventKey(item: IncidentRoomEvent): string {
  return item.event_id || item.id || `${item.role}:${item.ts}:${item.message}`;
}

function errorDetail(status: number, body: any, fallback: string): string {
  const detail = body && typeof body === 'object' ? body.detail || body.error : null;
  return detail ? String(detail) : `${fallback} (${status})`;
}

export function useIncidentConversation({
  incidentId,
  buyerToken,
  staffToken,
  ownerApiKey,
  onResolve,
}: {
  incidentId: string;
  buyerToken?: string | null;
  staffToken?: string | null;
  ownerApiKey?: string;
  onResolve?: (incidentId: string) => void;
}) {
  const [events, setEvents] = useState<IncidentRoomEvent[]>([]);
  const [mode, setMode] = useState<Mode>('poll');
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [remoteTyping, setRemoteTyping] = useState(false);
  const [resolved, setResolved] = useState(false);
  const typingTimerRef = useRef<number | null>(null);
  const typingSentAtRef = useRef(0);
  const forceSse = Boolean((import.meta as any).env?.VITE_FORCE_INCIDENT_SSE === 'true');

  const activeToken = buyerToken || staffToken || null;

  const postEvent = useCallback(async (payload: Record<string, unknown>) => {
    const path = activeToken
      ? `/api/v1/incidents/${encodeURIComponent(incidentId)}/room/message`
      : `/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/message`;
    const headers: Record<string, string> = { 'Content-Type': 'application/json', ...csrfHeaders() };
    if (activeToken) headers['x-incident-token'] = activeToken;
    else if (ownerApiKey) headers['x-api-key'] = ownerApiKey;
    const response = await fetch(apiUrl(path), {
      method: 'POST', credentials: 'include', headers, body: JSON.stringify(payload),
    });
    const body = await safeJson(response);
    if (!response.ok) throw new Error(errorDetail(response.status, body, 'send_failed'));
    return body;
  }, [activeToken, incidentId, ownerApiKey]);

  const acknowledge = useCallback((messageId: string) => {
    void postEvent({ event_type: 'read', message_id: messageId }).catch(() => undefined);
  }, [postEvent]);

  const consume = useCallback((raw: any) => {
    const incoming: IncidentRoomEvent[] = Array.isArray(raw)
      ? raw : Array.isArray(raw?.events) ? raw.events : [raw];
    if (!Array.isArray(incoming)) return;
    if (incoming.some((item) => String(item?.event_type || '').toLowerCase() === 'typing')) {
      setRemoteTyping(true);
      if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current);
      typingTimerRef.current = window.setTimeout(() => setRemoteTyping(false), 2400);
    }
    if (incoming.some((item) => ['incident_resolved', 'resolved', 'room_closed'].includes(String(item?.event_type || '').toLowerCase()))) {
      setResolved(true);
      onResolve?.(incidentId);
    }
    const readIds = new Set(incoming
      .filter((item) => String(item?.event_type || '').toLowerCase() === 'message_read')
      .map((item) => String(item?.meta?.message_id || '')).filter(Boolean));
    if (readIds.size) {
      setEvents((previous) => previous.map((item) => readIds.has(eventKey(item))
        ? { ...item, delivery_status: 'read' } : item));
    }
    const messages = incoming.filter((item) => {
      const kind = String(item?.event_type || 'message').toLowerCase();
      return !['typing', 'message_read', 'incident_resolved', 'resolved', 'room_closed'].includes(kind);
    });
    if (!messages.length) return;
    setRemoteTyping(false);
    setEvents((previous) => {
      const seen = new Set(previous.map(eventKey));
      return [...previous, ...messages.filter((item) => {
        const key = eventKey(item);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })];
    });
    const viewerIsBuyer = Boolean(buyerToken && !staffToken);
    for (const item of messages) {
      const role = String(item.role || '').toLowerCase();
      const remote = viewerIsBuyer ? role !== 'buyer' : role === 'buyer';
      const messageId = item.event_id || item.id;
      if (remote && messageId && !['human_joined', 'human_left'].includes(String(item.event_type || '').toLowerCase())) {
        acknowledge(messageId);
      }
    }
  }, [acknowledge, buyerToken, incidentId, onResolve, staffToken]);

  useEffect(() => {
    let mounted = true;
    const checkStatus = async () => {
      try {
        const path = activeToken
          ? `/api/v1/incidents/${encodeURIComponent(incidentId)}/summary/public`
          : `/api/v1/admin/incidents/${encodeURIComponent(incidentId)}`;
        const headers: Record<string, string> = {};
        if (activeToken) headers['x-incident-token'] = activeToken;
        else if (ownerApiKey) headers['x-api-key'] = ownerApiKey;
        const response = await fetch(apiUrl(path), { credentials: 'include', headers });
        const body = await safeJson(response);
        if (!response.ok) return;
        const status = String(body?.status || '').toLowerCase();
        if (mounted) setResolved(status === 'resolved' || status === 'closed');
      } catch { /* best effort */ }
    };
    void checkStatus();
    const timer = window.setInterval(checkStatus, 7000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [activeToken, incidentId, ownerApiKey]);

  useEffect(() => {
    let mounted = true;
    let ws: WebSocket | null = null;
    let stream: EventSource | null = null;
    setConnectionError(null);
    setSendError(null);

    if (!buyerToken && !staffToken && !forceSse) {
      try {
        ws = new WebSocket(wsUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/ws`));
        ws.onopen = () => { if (mounted) { setMode('ws'); setConnectionError(null); } };
        ws.onmessage = (event) => { try { consume(JSON.parse(event.data)); } catch { /* malformed */ } };
        ws.onerror = () => { if (mounted) setConnectionError('WebSocket unavailable; authenticated event stream remains active.'); };
      } catch { ws = null; }
    }

    const connectStream = async () => {
      try {
        let token = activeToken;
        if (!token && ownerApiKey) {
          const response = await fetch(apiUrl(`/api/v1/admin/incidents/${encodeURIComponent(incidentId)}/room/token`), {
            method: 'POST', credentials: 'include', headers: { ...csrfHeaders(), 'x-api-key': ownerApiKey },
          });
          const body = await safeJson(response);
          if (!response.ok) throw new Error(errorDetail(response.status, body, 'token_issue_failed'));
          token = body?.staff_token ? String(body.staff_token) : null;
        }
        if (!token) throw new Error('incident_token_unavailable');
        setIncidentTokenCookie(incidentId, token);
        stream = new EventSource(apiUrl(`/api/v1/incidents/${encodeURIComponent(incidentId)}/room/stream?token=${encodeURIComponent(token)}`));
        stream.onopen = () => { if (mounted) { setMode('sse'); setConnectionError(null); } };
        stream.onmessage = (event) => { try { consume(JSON.parse(event.data)); } catch { /* malformed */ } };
        stream.onerror = () => { if (mounted) setConnectionError('Incident stream disconnected. Reconnecting...'); };
      } catch (error: any) {
        if (mounted) { setMode('poll'); setConnectionError(`Room connection failed: ${error?.message || 'unknown_error'}.`); }
      }
    };
    void connectStream();
    return () => {
      mounted = false;
      clearIncidentTokenCookie(incidentId);
      try { ws?.close(); } catch { /* ignore */ }
      try { stream?.close(); } catch { /* ignore */ }
    };
  }, [activeToken, buyerToken, consume, forceSse, incidentId, ownerApiKey, staffToken]);

  useEffect(() => () => {
    if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current);
  }, []);

  const sendTyping = useCallback(async () => {
    const now = Date.now();
    if (now - typingSentAtRef.current < 800) return;
    typingSentAtRef.current = now;
    try { await postEvent({ event_type: 'typing' }); } catch { /* ephemeral */ }
  }, [postEvent]);

  const sendMessage = useCallback(async (message: string) => {
    setSendError(null);
    try { await postEvent({ message }); }
    catch (error: any) { setSendError(`Send failed: ${error?.message || 'unknown_error'}.`); throw error; }
  }, [postEvent]);

  return {
    events, mode, connectionError, sendError, remoteTyping, resolved, setResolved,
    sendTyping, sendMessage,
  };
}
