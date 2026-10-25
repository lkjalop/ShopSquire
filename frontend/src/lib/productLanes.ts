import {formatMoney, normalizeCurrency} from './money';

export type DeviceLane = 'windows' | 'macbook' | 'tablet_chromebook' | 'catalogue';

type DisplayProduct = {
  name?: string;
  price?: unknown;
  price_cents?: unknown;
  currency?: string;
  features?: string[];
  specs?: Record<string, unknown>;
};

/** Display grouping only. An absent OS observation stays unclassified. */
export function laneForProduct(product: DisplayProduct): DeviceLane {
  const name=String(product.name || '').toLowerCase();
  const observed=[name,...(Array.isArray(product.features) ? product.features : []),product.specs?.operating_system,product.specs?.os]
    .filter(value=>typeof value==='string').join(' ').toLowerCase();
  if (/\bmacbook\b/.test(name)) return 'macbook';
  if (/\b(?:chromebook|chrome os|tablet|ipad)\b/.test(observed)) return 'tablet_chromebook';
  if (/\bwindows\b/.test(observed)) return 'windows';
  return 'catalogue';
}

export function laneTitle(lane: DeviceLane): string {
  if (lane==='macbook') return 'MacBook options';
  if (lane==='tablet_chromebook') return 'Tablet / Chromebook options';
  if (lane==='windows') return 'Windows options';
  return 'Catalogue options';
}

export function laneSummary(_lane: DeviceLane, items: DisplayProduct[], _budgetStatus?: string, _query?: string): string {
  if (!items.length) return 'No catalogue observations in this group.';
  const prices=items.map(item=>{
    const price=Number(item.price);
    const cents=Number(item.price_cents);
    return Number.isFinite(price) && price>0 ? price
      : Number.isFinite(cents) && cents>0 ? cents/100 : null;
  }).filter((value):value is number=>value!==null);
  const currencies=new Set(items.map(item=>typeof item.currency==='string' && /^[a-z]{3}$/i.test(item.currency.trim())
    ? normalizeCurrency(item.currency) : null));
  const currency=currencies.size===1 ? [...currencies][0] : null;
  const priceDescription=currencies.has(null)
    ? 'Currency unknown; no comparable price range is available.'
    : currencies.size>1
    ? 'Multiple currencies (conversion required before comparison).'
    : !currency ? 'Currency unknown; no comparable price range is available.'
      : !prices.length ? 'Price not available.'
        : `Observed prices: ${formatMoney(Math.min(...prices),currency)} to ${formatMoney(Math.max(...prices),currency)}.`;
  return `Catalogue snapshots. ${priceDescription} Verify compatibility and current availability before proceeding.`;
}
