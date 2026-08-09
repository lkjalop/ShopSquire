export type NonRecommendationOutcome = {
  kind: 'blocked' | 'degraded';
  message: string;
  preserveCurrentView: true;
  authority: 'no_state_change';
};

/**
 * Convert a governed backend refusal/degradation into a UI outcome without
 * letting it fall through to recommendation rendering.  These responses are
 * deliberately non-mutating: the current product, cart, and procurement case
 * remain visible and deterministic controls continue to work.
 */
export function nonRecommendationOutcome(payload: any): NonRecommendationOutcome | null {
  if (!payload || (payload.blocked !== true && payload.degraded !== true)) return null;

  const kind: NonRecommendationOutcome['kind'] = payload.blocked === true ? 'blocked' : 'degraded';
  const supplied = String(
    payload.assistant_message
      || payload.message
      || payload.blocked_detail?.message
      || '',
  ).trim();
  const reason = String(payload.quota_reason || payload.degraded_reason || '').trim();
  const defaultMessage = kind === 'blocked'
    ? 'AI narration is unavailable for this request. Your product, cart, and procurement case are unchanged.'
    : 'AI narration is temporarily degraded. Your product, cart, and procurement case are unchanged; deterministic controls remain available.';

  return {
    kind,
    message: supplied || (reason ? `${defaultMessage} (${reason})` : defaultMessage),
    preserveCurrentView: true,
    authority: 'no_state_change',
  };
}
