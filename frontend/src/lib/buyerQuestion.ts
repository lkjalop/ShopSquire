export type BuyerQuestionLike = {
  id?: string | null;
  goal?: string | null;
  text?: string | null;
  options?: unknown[] | null;
};

/** Keep refusal/status copy out of the question-only narrowing affordance. */
export function isActionableBuyerQuestion(value: BuyerQuestionLike | null | undefined): boolean {
  if (!value) return false;
  return String(value.text || '').trim().endsWith('?')
    || (Array.isArray(value.options) && value.options.length > 0);
}

/** Research authority is rendered once in the dedicated identity/research card. */
export function isResearchAuthorityQuestion(value: BuyerQuestionLike | null | undefined): boolean {
  if (!value) return false;
  const id = String(value.id || '').trim().toLowerCase();
  const goal = String(value.goal || '').trim().toLowerCase();
  return id === 'workload_requirements'
    || id === 'research_scope'
    || goal === 'resolve_named_workload'
    || goal === 'resolve_research_scope';
}
