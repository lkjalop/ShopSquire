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

export function useDecisionTraceData({ active, caseId }: { active: boolean; caseId: string | null }) {
  const [data, setData] = useState<any | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'unavailable'>('idle');
  const uid = useMemo(() => {
    try { return sessionStorage.getItem('uid') || 'demo-user'; } catch { return 'demo-user'; }
  }, []);
  const tenantId = useMemo(() => {
    try { return sessionStorage.getItem('tenant_id') || 'default'; } catch { return 'default'; }
  }, []);

  useEffect(() => {
    if (!active || !caseId) { setStatus('idle'); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort('deadline_exceeded'), 5000);
    setStatus('loading');
    fetch(apiUrl(`/api/v1/shopping-cases/${encodeURIComponent(caseId)}/decision-runs?uid=${encodeURIComponent(uid)}`), {
      credentials: 'include', signal: controller.signal, headers: { 'x-tenant-id': tenantId },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`http_${response.status}`);
        return response.json();
      })
      .then((value) => { setData(value); setStatus('ready'); })
      .catch(() => { if (!controller.signal.aborted) setStatus('unavailable'); })
      .finally(() => window.clearTimeout(timer));
    return () => { window.clearTimeout(timer); controller.abort('trace_closed'); };
  }, [active, caseId, tenantId, uid]);

  return { data, status };
}
