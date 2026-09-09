export const ACCESSORY_UPSELL_TRACE_LABEL = 'Accessory upsell trace';

export function slateConsistencyLabel(recorded: boolean, matches: boolean, count: number): string {
  if (!recorded) return 'Not recorded';
  if (!matches) return 'Mismatch — review required';
  return count === 0 ? 'Empty — no products' : 'Matches recorded order';
}

export function shouldShowMissingAnchorReasoning(
  anchorSections: unknown,
  rankedProducts: unknown,
): boolean {
  const hasAnchors = Array.isArray(anchorSections) && anchorSections.length > 0;
  const hasRankedProducts = Array.isArray(rankedProducts) && rankedProducts.length > 0;
  return !hasAnchors && !hasRankedProducts;
}
