import { useEffect, useRef, useState } from 'react';
import traceClient from './traceClient';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8080/api/v1';
const API_KEY = import.meta.env.VITE_API_KEY || 'local-developer-key';

export function useDecisionTrace() {
  const [events, setEvents] = useState([]);
  const [lastSummary, setLastSummary] = useState(null);
  const activeTraceRef = useRef(null);

  const _onSummary = (payload) => {
    try { if (payload && payload.available) setLastSummary(payload); } catch (e) {}
  };

  const _onTraceItems = (items) => {
    try {
      if (!Array.isArray(items)) return;
      setEvents((prev) => {
        const existing = new Set(prev.map((i) => i.id));
        const mapped = items.map((i) => ({
          id: i.id || `evt-${i.created_at || Date.now()}`,
          time: i.created_at || new Date().toISOString(),
          type: (i?.payload?._original_event_type || i?.payload?.original_event_type || i.event_type || 'event'),
          source: i.source_id,
          target: i.target_id,
          trace_id: i.trace_id,
          payload: i.payload || {},
        }));
        const merged = [...mapped.filter((m) => !existing.has(m.id)), ...prev];
        return merged.slice(0, 50);
      });
    } catch (e) {}
  };

  const subscribe = (traceId, uid = 'guest_user') => {
    activeTraceRef.current = traceId;
    try {
      const url = `${API_BASE}/decisions/stream?uid=${encodeURIComponent(uid)}&api_key=${encodeURIComponent(API_KEY)}`;
      traceClient.startSummary(url, _onSummary);
    } catch (e) {}

    try {
      const url = `${API_BASE}/decisions/${encodeURIComponent(traceId)}/events/stream`;
      const pollFn = async () => {
        try {
          const res = await fetch(
            `${API_BASE}/decisions/${encodeURIComponent(activeTraceRef.current)}/query?include_events=true`,
            {
              headers: { 'x-api-key': API_KEY },
            }
          );
          if (!res.ok) return;
          const data = await res.json();
          const items = Array.isArray(data.events) ? data.events : [];
          _onTraceItems(items);
        } catch (e) {}
      };
      traceClient.startTrace(url, _onTraceItems, pollFn, 4000);
    } catch (e) {}
  };

  const unsubscribe = () => {
    try { traceClient.stopSummary(); } catch (e) {}
    try { traceClient.stopTrace(); } catch (e) {}
    activeTraceRef.current = null;
  };

  // Ensure polling continues if SSE unavailable (traceClient already handles poll scheduling)
  useEffect(() => {
    return () => { unsubscribe(); };
  }, []);

  const filtered = events.filter((e) => e.type === 'cv_job_queued' || e.type === 'fraud_job_queued');

  return { events, filtered, lastSummary, subscribe, unsubscribe, traceClient };
}
