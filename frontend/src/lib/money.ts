export function normalizeCurrency(value: unknown): string {
  const code = String(value || 'USD').trim().toUpperCase();
  return /^[A-Z]{3}$/.test(code) ? code : 'USD';
}

export function formatMoney(value: number, currency: unknown = 'USD'): string {
  return Number(value).toLocaleString('en-AU', {
    style: 'currency',
    currency: normalizeCurrency(currency),
    currencyDisplay: 'code',
    maximumFractionDigits: 0,
  });
}

export function formatProductPrice(product: any): string {
  const direct = Number(product?.price);
  const cents = Number(product?.price_cents);
  const value = Number.isFinite(direct) && direct > 0
    ? direct
    : Number.isFinite(cents) && cents > 0 ? cents / 100 : 0;
  return value > 0 ? formatMoney(value, product?.currency) : '—';
}
