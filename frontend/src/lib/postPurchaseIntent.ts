const TRACKING_NOUN = String.raw`(?:order|package|delivery|shipment|parcel)`;

const EXPLICIT_TRACKING = new RegExp(
  String.raw`\b(?:track|where(?:'s| is)|status of)\b.{0,24}\b${TRACKING_NOUN}\b|\border\s+status\b`,
  'i',
);
const SHIPMENT_STATE = new RegExp(
  String.raw`\b(?:has|have)\b.{0,30}\b${TRACKING_NOUN}\b.{0,20}\b(?:shipped|arrived|delivered|dispatched)\b`,
  'i',
);
const ARRIVAL_QUESTION = /\bwhen\b.{0,40}\b(?:arrive|delivered|ship|get\s+here)\b/i;
const POST_PURCHASE_ANCHOR = new RegExp(
  String.raw`(?:\b(?:my|our|existing|current|placed|confirmed)\s+${TRACKING_NOUN}\b|\border\s*(?:#|number|ref(?:erence)?[:\s-])\s*[a-z0-9-]+\b)`,
  'i',
);

/**
 * Identify post-purchase tracking requests that the storefront cannot execute.
 * Prospective fulfilment questions deliberately return false so quantity,
 * deadline and sourcing logic can reach the backend.
 */
export function isUnsupportedPostPurchaseTracking(query: string): boolean {
  const text = String(query || '').trim();
  if (!text) return false;
  if (EXPLICIT_TRACKING.test(text) || SHIPMENT_STATE.test(text)) return true;
  return ARRIVAL_QUESTION.test(text) && POST_PURCHASE_ANCHOR.test(text);
}
