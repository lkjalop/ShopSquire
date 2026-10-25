import { useEffect, useState } from 'react';
import { apiUrl, getSplitOffer, type SplitOfferResult } from '../lib/api';
import { procurementDraftPending } from '../lib/procurementGateDisplay';

type LoadStatus = 'idle' | 'loading' | 'ready' | 'not_applicable' | 'error';
type Snapshot = { key: string; status: LoadStatus; error: string | null; primaryCase: any;
  cases: any[]; history: any; allocation: any; journey: any[] | null };
const empty = (key: string, status: LoadStatus = 'idle'): Snapshot => ({
  key, status, error: null, primaryCase: null, cases: [], history: null, allocation: null, journey: null,
});

async function fetchJson(url: string, signal: AbortSignal, headers?: HeadersInit): Promise<any> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) controller.abort();
  signal.addEventListener('abort', abort, { once: true });
  const timeout = window.setTimeout(abort, 8000);
  try {
    const response = await fetch(url, { credentials: 'include', headers, signal: controller.signal });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener('abort', abort);
  }
}

export function useProcurementTrace({ active, traceId, apiKey, canSeeOperatorDraft, revision }: {
  active: boolean; traceId: string; apiKey: string; canSeeOperatorDraft: boolean; revision: string;
}) {
  const key = `${traceId}\u001f${revision}\u001f${canSeeOperatorDraft}`;
  const [snapshot, setSnapshot] = useState<Snapshot>(() => empty(key));
  const [selection, setSelection] = useState({ traceId, caseId: null as string | null });
  const caseId = selection.traceId === traceId ? selection.caseId : null;
  const setCaseId = (value: string | null) => setSelection({ traceId, caseId: value });
  const [retryState, setRetry] = useState({ key, count: 0 });
  const retry = retryState.key === key ? retryState.count : 0;
  const [split, setSplit] = useState<{ key: string; value: SplitOfferResult | null }>({ key, value: null });
  const current = snapshot.key === key ? snapshot : empty(key, active ? 'loading' : 'idle');

  useEffect(() => {
    if (!active || !traceId) return;
    const controller = new AbortController();
    const { signal } = controller;
    setSnapshot(empty(key, 'loading'));
    const headers = apiKey ? { 'x-api-key': apiKey } : undefined;
    const load = async () => {
      try {
        const suffix = canSeeOperatorDraft ? '/all/operator-view' : '/all';
        const allView = await fetchJson(apiUrl(`/api/v1/fulfillment/cases/by-trace/${encodeURIComponent(traceId)}${suffix}`), signal, headers);
        if (signal.aborted) return;
        const rows = Array.isArray(allView?.cases) ? allView.cases : [];
        const activeRows = rows.filter((item: any) => String(item?.state || '').toUpperCase() !== 'SUPERSEDED');
        const cases = activeRows.length ? activeRows : rows;
        const primaryCase = cases.find((item: any) => item.case_id === caseId) || cases[0] || null;
        if (!primaryCase) {
          setSnapshot(empty(key, 'not_applicable'));
          return;
        }
        const group = String(allView?.order_group_id || '');
        const orderId = canSeeOperatorDraft && group.startsWith('order-') ? group.slice(6) : '';
        const sku = String(primaryCase?.state_json?.availability?.item_ref || primaryCase?.state_json?.draft?.commercial_scope?.item_ref || '');
        const resolvedId = primaryCase.case_id || caseId;
        const [history, allocation, journey] = await Promise.all([
          orderId ? fetchJson(apiUrl(`/api/v1/fulfillment/cases/by-order/${encodeURIComponent(orderId)}`), signal, headers) : null,
          canSeeOperatorDraft ? fetchJson(apiUrl(`/api/v1/admin/allocation/workbench${sku ? `?sku=${encodeURIComponent(sku)}` : ''}`), signal, headers) : null,
          resolvedId ? fetchJson(apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(resolvedId)}/journey`), signal, headers) : null,
        ]);
        if (!signal.aborted) setSnapshot({ key, status: 'ready', error: null, cases, primaryCase,
          history: history?.case_count ? history : allView?.amendment_history || null,
          allocation: allocation?.summary ? allocation : null,
          journey: Array.isArray(journey?.journey) ? journey.journey : null });
      } catch (error) {
        if (!signal.aborted) setSnapshot({ ...empty(key, 'error'), error: error instanceof Error ? error.message : 'request_failed' });
      }
    };
    void load();
    return () => controller.abort();
  }, [active, traceId, apiKey, canSeeOperatorDraft, revision, key, caseId, retry]);

  useEffect(() => {
    if (!active || current.status !== 'ready' || !procurementDraftPending(current.primaryCase) || retry >= 4) return;
    const timer = window.setTimeout(() => setRetry({ key, count: retry + 1 }), 1000);
    return () => window.clearTimeout(timer);
  }, [active, key, current.status, current.primaryCase, retry]);

  useEffect(() => {
    if (!active || current.status !== 'not_applicable') return;
    let alive = true;
    const uid = (() => { try { return sessionStorage.getItem('uid') || 'demo-user'; } catch { return 'demo-user'; } })();
    getSplitOffer(uid).then(value => {
      if (alive) setSplit({ key, value: value?.split && !value.split.fully_in_stock ? value : null });
    }).catch(() => { if (alive) setSplit({ key, value: null }); });
    return () => { alive = false; };
  }, [active, key, current.status]);

  return { ...current, caseId, setCaseId, pendingSplit: split.key === key ? split.value : null,
    loading: current.status === 'loading' };
}
