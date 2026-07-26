export type PendingBulkBudget = {
  total_cents?: number;
  total?: number;
  scope?: string;
  [key: string]: unknown;
};

export function normalizePendingBulkBudget(
  raw: unknown,
  confirmedSlots: unknown,
): PendingBulkBudget | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;

  const budget = { ...(raw as Record<string, unknown>) };
  const slots = confirmedSlots && typeof confirmedSlots === 'object' && !Array.isArray(confirmedSlots)
    ? confirmedSlots as Record<string, unknown>
    : {};
  const scope = String(
    budget.scope
      || budget.budget_scope
      || slots.budget_scope
      || '',
  ).trim().toLowerCase();

  return {
    ...budget,
    ...(scope ? { scope } : {}),
  };
}
