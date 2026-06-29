// Friendly messaging for procurement action failures. A 409 is almost always benign — an idempotent replay
// (the action already applied) or a state conflict (the case moved past this step) — and should read as a
// calm "refreshing" notice, not a scary error. Anything else surfaces the raw message. Pure + unit-tested.

export interface ActionMessage { calm: boolean; message: string }

export function procurementActionMessage(err: any): ActionMessage {
  const status = Number(err?.status || 0);
  const detail = String(err?.detail || err?.message || '').toLowerCase();
  if (status === 409) {
    if (detail.includes('idempot') || detail.includes('replay') || detail.includes('already')) {
      return { calm: true, message: 'That action was already applied — refreshing the case.' };
    }
    if (detail.includes('illegal_transition') || detail.includes('terminal') || detail.includes('not_permitted')) {
      return { calm: true, message: 'The case has already moved past this step — refreshing.' };
    }
    if (detail.includes('rate_limit')) {
      return { calm: true, message: 'Too many requests just now — please retry in a moment.' };
    }
    return { calm: true, message: 'This action conflicts with the current case state — refreshing.' };
  }
  return { calm: false, message: err?.message || 'action failed' };
}
