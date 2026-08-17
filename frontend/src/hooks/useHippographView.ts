import { useCallback, useEffect, useState } from 'react';

import { apiUrl, safeJson } from '../lib/api';

export type HippographViewPurpose = 'what_changed' | 'historical_knowledge' | 'supplier_fulfilment';

export function useHippographView({
  active, seedId, caseId, apiKey,
}: {
  active: boolean;
  seedId: string;
  caseId?: string | null;
  apiKey: string;
}) {
  const [purpose, setPurpose] = useState<HippographViewPurpose>('what_changed');
  const [view, setView] = useState<any | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'available' | 'unavailable'>('idle');

  const load = useCallback(async (nextPurpose: HippographViewPurpose) => {
    if (!active || !seedId || !apiKey) return;
    const controller = new AbortController();
    const deadline = window.setTimeout(() => controller.abort(), 5000);
    setPurpose(nextPurpose);
    setStatus('loading');
    try {
      const query = new URLSearchParams({ seed_id: seedId, purpose: nextPurpose });
      if (caseId) query.set('case_id', caseId);
      const response = await fetch(apiUrl(`/api/v1/hippograph/view?${query.toString()}`), {
        credentials: 'include', signal: controller.signal, headers: { 'x-api-key': apiKey },
      });
      const payload = await safeJson(response);
      if (!response.ok) throw new Error(`hippograph_view_${response.status}`);
      setView(payload);
      setStatus('available');
    } catch {
      if (!controller.signal.aborted) setView(null);
      setStatus('unavailable');
    } finally {
      window.clearTimeout(deadline);
    }
  }, [active, apiKey, caseId, seedId]);

  useEffect(() => {
    setView(null);
    setStatus('idle');
    setPurpose('what_changed');
  }, [caseId, seedId]);

  return { purpose, view, status, load };
}
