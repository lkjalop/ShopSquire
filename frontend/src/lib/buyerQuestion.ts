export type BuyerQuestionLike = {
  text?: string | null;
  options?: unknown[] | null;
};

/** Keep refusal/status copy out of the question-only narrowing affordance. */
export function isActionableBuyerQuestion(value: BuyerQuestionLike | null | undefined): boolean {
  if (!value) return false;
  return String(value.text || '').trim().endsWith('?')
    || (Array.isArray(value.options) && value.options.length > 0);
}
