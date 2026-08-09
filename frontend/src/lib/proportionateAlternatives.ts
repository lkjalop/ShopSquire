import type { ShelfProduct } from '../components/ProductShelvesPanel';

export type ProportionateAlternative = {
  sku: string;
  title: string;
  priceCents: number;
  currency: string;
  savingsCents: number;
  savingsPercent: number;
  fitStatus: 'qualified' | 'conditional';
  compromise: string;
};

export function selectProportionateAlternatives(
  preferred: ShelfProduct,
  candidates: ShelfProduct[],
  minimumSavingsPercent = 20,
): ProportionateAlternative[] {
  if (preferred.price_cents <= 0) return [];
  const maximumPrice = Math.floor(preferred.price_cents * (1 - minimumSavingsPercent / 100));
  const ordered = candidates
    .filter((candidate) => (
      candidate.product.sku !== preferred.product.sku
      && candidate.currency === preferred.currency
      && candidate.product.form_factor === preferred.product.form_factor
      && candidate.fit_status !== 'failed'
      && !(candidate.misses || []).length
      && candidate.price_cents <= maximumPrice
    ))
    .sort((left, right) => (
      (right.relevance_score - left.relevance_score)
      || (left.price_cents - right.price_cents)
      || left.product.sku.localeCompare(right.product.sku)
    ));
  const seen = new Set<string>();
  const selected: ProportionateAlternative[] = [];
  for (const candidate of ordered) {
      if (seen.has(candidate.product.sku)) continue;
      seen.add(candidate.product.sku);
      const savingsCents = preferred.price_cents - candidate.price_cents;
      const gaps = [...(candidate.compromises || []), ...(candidate.unknowns || [])];
      selected.push({
        sku: candidate.product.sku,
        title: candidate.title,
        priceCents: candidate.price_cents,
        currency: candidate.currency,
        savingsCents,
        savingsPercent: Math.round((savingsCents / preferred.price_cents) * 100),
        fitStatus: candidate.fit_status,
        compromise: gaps.length
          ? `Trade-off or unverified area: ${gaps.slice(0, 2).join(', ')}.`
          : 'No verified minimum miss; review the detailed evidence before substitution.',
      });
      if (selected.length === 3) break;
  }
  return selected;
}
