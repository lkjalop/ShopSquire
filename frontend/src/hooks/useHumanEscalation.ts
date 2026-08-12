import { useCallback, useState } from 'react';

export type HumanEscalationPayload = {
  incident_id?: string;
  buyer_token?: string;
};

export function useHumanEscalation() {
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [buyerToken, setBuyerToken] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const openFromPayload = useCallback((payload: HumanEscalationPayload): string | null => {
    const nextIncidentId = String(payload?.incident_id || '').trim();
    if (!nextIncidentId) return null;
    setIncidentId(nextIncidentId);
    setBuyerToken(payload?.buyer_token ? String(payload.buyer_token) : null);
    setOpen(true);
    return nextIncidentId;
  }, []);

  const close = useCallback(() => setOpen(false), []);

  return { open, incidentId, buyerToken, openFromPayload, close };
}
