import type { PendingCartPlan } from '../components/PendingCartChangeCard';

export function pendingCartPlanFromHumanEvent(value: unknown): PendingCartPlan | null {
  if (!value || typeof value !== 'object') return null;
  const proposal = value as Record<string, any>;
  const planId = String(proposal.plan_id || proposal.planId || '').trim();
  const plan = proposal.plan && typeof proposal.plan === 'object' ? proposal.plan : proposal;
  const ops = Array.isArray(plan.ops) ? plan.ops : [];
  if (!planId || ops.length === 0) return null;
  return {
    planId,
    ops,
    expiresAt: String(proposal.expires_at || proposal.expiresAt || '').trim() || undefined,
  };
}
