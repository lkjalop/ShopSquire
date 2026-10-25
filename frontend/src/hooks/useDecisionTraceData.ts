import { useEffect, useMemo, useState } from 'react';

import { apiUrl } from '../lib/api';

export type DecisionRunTrace = {
  run_id: string;
  case_revision: number;
  knowledge_cutoff: string;
  evaluation_time: string;
  status: string;
  stage_receipts: Array<Record<string, any>>;
  invalidations: Array<Record<string, any>>;
  temporal_conflicts: Array<Record<string, any>>;
  evidence_watermarks: Array<Record<string, any>>;
  commercial_authority_granted: false;
};

export function shoppingCaseIdFromTraceEvents(events: Array<any>): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const payload = events[index]?.payload || {};
    const candidates = [
      payload?.procurement_decision_run?.case_id,
      payload?.case_id,
      payload?.shopping_case_id,
      payload?.ambiguity_exploration?.case_id,
    ];
    const match = candidates.find((value) => /^sc-|^case-/.test(String(value || '')));
    if (match) return String(match);
  }
  return null;
}

export function useDecisionTraceData({ active, caseId, revision }: { active: boolean; caseId: string | null; revision?: number }) {
  const [data, setData] = useState<any | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'unavailable'>('idle');
  const uid = useMemo(() => {
    try { return sessionStorage.getItem('uid') || 'demo-user'; } catch { return 'demo-user'; }
  }, []);
  const tenantId = useMemo(() => {
    const configured = String(import.meta.env.VITE_STOREFRONT_TENANT_ID || '').trim();
    if (configured) return configured;
    try { return sessionStorage.getItem('tenant_id')?.trim() || 'default'; } catch { return 'default'; }
  }, []);

  useEffect(() => {
    if (!active || !caseId) { setData(null); setStatus('idle'); return; }
    let disposed = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      controller.abort('deadline_exceeded');
      if (!disposed) setStatus('unavailable');
    }, 8000); // Match the audit transport budget, including browser connection queueing.
    setData(null);
    setStatus('loading');
    fetch(apiUrl(`/api/v1/shopping-cases/${encodeURIComponent(caseId)}/decision-runs?uid=${encodeURIComponent(uid)}`), {
      credentials: 'include', signal: controller.signal, headers: { 'x-tenant-id': tenantId },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`http_${response.status}`);
        return response.json();
      })
      .then((value) => { if (!disposed) { setData(value); setStatus('ready'); } })
      .catch(() => { if (!disposed) setStatus('unavailable'); })
      .finally(() => window.clearTimeout(timer));
    return () => { disposed = true; window.clearTimeout(timer); controller.abort('trace_closed'); };
  }, [active, caseId, revision, tenantId, uid, attempt]);

  return { data, status, retry: () => setAttempt(value => value + 1) };
}
