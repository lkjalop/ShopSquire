import { useCallback, useEffect, useState } from 'react';

import { apiUrl, getSplitOffer, type SplitOfferResult } from '../lib/api';
import { procurementDraftPending } from '../lib/procurementGateDisplay';

async function fetchJsonWithDeadline(url: string, init: RequestInit = {}, deadlineMs = 8000): Promise<any> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort('deadline_exceeded'), deadlineMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) throw new Error(`http_${response.status}`);
    return await response.json();
  } finally {
    window.clearTimeout(timeout);
  }
}

export function useProcurementTrace({
  active,
  traceId,
  apiKey,
  canSeeOperatorDraft,
  revision,
}: {
  active: boolean;
  traceId: string;
  apiKey: string;
  canSeeOperatorDraft: boolean;
  revision: string;
}) {
  const [caseId, setCaseId] = useState<string | null>(null);
  const [primaryCase, setPrimaryCase] = useState<any | null>(null);
  const [cases, setCases] = useState<any[]>([]);
  const [history, setHistory] = useState<any | null>(null);
  const [allocation, setAllocation] = useState<any | null>(null);
  const [journey, setJourney] = useState<any[] | null>(null);
  const [pendingSplit, setPendingSplit] = useState<SplitOfferResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!active || loading || primaryCase || caseId) return;
    let alive = true;
    const timer = window.setTimeout(() => {
      const uid = (() => { try { return sessionStorage.getItem('uid') || 'demo-user'; } catch { return 'demo-user'; } })();
      getSplitOffer(uid)
        .then((result) => { if (alive) setPendingSplit(result?.split && !result.split.fully_in_stock ? result : null); })
        .catch(() => { if (alive) setPendingSplit(null); });
    }, 750);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [active, loading, primaryCase, caseId]);

  const load = useCallback(async () => {
    if (!traceId) return;
    setLoading(true);
    try {
      const headers = apiKey ? { 'x-api-key': apiKey } : undefined;
      const casePath = canSeeOperatorDraft
        ? `/api/v1/fulfillment/cases/by-trace/${encodeURIComponent(traceId)}/all/operator-view`
        : `/api/v1/fulfillment/cases/by-trace/${encodeURIComponent(traceId)}/all`;
      const allView = await fetchJsonWithDeadline(apiUrl(casePath), { credentials: 'include', headers }).catch(() => null);
      const rows = Array.isArray(allView?.cases) ? allView.cases : [];
      const activeRows = rows.filter((item: any) => String(item?.state || '').toUpperCase() !== 'SUPERSEDED');
      const visible = activeRows.length ? activeRows : rows;
      const primary = visible[0] || null;
      setCases(visible);
      setPrimaryCase(primary && (primary.case_id || primary.state) ? primary : null);
      const orderGroupId = String(allView?.order_group_id || '');
      const embeddedHistory = allView?.amendment_history?.case_count ? allView.amendment_history : null;
      const resolvedCaseId = primary?.case_id || caseId;
      const orderId = canSeeOperatorDraft && orderGroupId.startsWith('order-') ? orderGroupId.slice(6) : '';
      const sku = canSeeOperatorDraft && primary ? String(
        primary?.state_json?.availability?.item_ref || primary?.state_json?.draft?.commercial_scope?.item_ref || '',
      ).trim() : '';
      const [historyValue, allocationValue, journeyValue] = await Promise.all([
        orderId ? fetchJsonWithDeadline(apiUrl(`/api/v1/fulfillment/cases/by-order/${encodeURIComponent(orderId)}`), { credentials: 'include', headers }).catch(() => null) : null,
        canSeeOperatorDraft && primary ? fetchJsonWithDeadline(apiUrl(`/api/v1/admin/allocation/workbench${sku ? `?sku=${encodeURIComponent(sku)}` : ''}`), { credentials: 'include', headers }).catch(() => null) : null,
        resolvedCaseId ? fetchJsonWithDeadline(apiUrl(`/api/v1/fulfillment/cases/${encodeURIComponent(resolvedCaseId)}/journey`), { credentials: 'include', headers }).catch(() => null) : null,
      ]);
      setHistory(historyValue?.case_count ? historyValue : embeddedHistory);
      setAllocation(allocationValue?.summary ? allocationValue : null);
      setJourney(Array.isArray(journeyValue?.journey) ? journeyValue.journey : null);
    } finally {
      setLoading(false);
    }
  }, [apiKey, canSeeOperatorDraft, caseId, traceId]);

  useEffect(() => { if (active && traceId) void load(); }, [active, traceId, caseId, revision, retry, load]);
  useEffect(() => {
    if (!active || !caseId || !procurementDraftPending(primaryCase) || retry >= 4) return;
    const timer = window.setTimeout(() => setRetry((value) => value + 1), 1000);
    return () => window.clearTimeout(timer);
  }, [active, caseId, primaryCase, retry]);
  useEffect(() => {
    setCaseId(null); setPrimaryCase(null); setCases([]); setHistory(null); setAllocation(null);
    setJourney(null); setPendingSplit(null); setRetry(0);
  }, [traceId]);

  return { caseId, setCaseId, primaryCase, cases, history, allocation, journey, pendingSplit, loading };
}
