export const ACCESSORY_UPSELL_TRACE_LABEL = 'Accessory upsell trace';

export function shouldShowMissingAnchorReasoning(
  anchorSections: unknown,
  rankedProducts: unknown,
): boolean {
  const hasAnchors = Array.isArray(anchorSections) && anchorSections.length > 0;
  const hasRankedProducts = Array.isArray(rankedProducts) && rankedProducts.length > 0;
  return !hasAnchors && !hasRankedProducts;
}
