/**
 * Which cart items were carried over from a PREVIOUS session?
 *
 * The App snapshots the cart's SKUs on the first cart read of the session (`initialSkus`). Anything in
 * the current cart that was already there at session start is "previous-session" — the set the buyer
 * may want to clear WITHOUT losing what they just added ("Clear previous (N)" vs "Clear" everything).
 * A session that starts with an empty cart snapshots [] → nothing is ever labelled previous. Pure +
 * deterministic so it's unit-testable in isolation.
 */
export function previousSessionSkus(currentSkus: string[], initialSkus: string[] | null): string[] {
  if (!initialSkus || initialSkus.length === 0) return [];
  const init = new Set(initialSkus.map((s) => String(s)));
  return (currentSkus || []).filter((s) => init.has(String(s)));
}

type CartLike = { sku: string; name?: string };

const _CLEAR_VERB = /\b(?:clear|empty|wipe|reset|remove|delete|drop|get\s+rid\s+of)\b/i;
const _KEEP_CUE = /\b(?:keep|except|but\s+(?:keep|leave)|leave|save|apart\s+from|other\s+than|without\s+removing)\b/i;
const _CART_OBJ = /\b(?:cart|everything|all|the\s+rest|items?|units?|basket)\b/i;
const _LATEST = /\b(?:latest|newest|last|most\s+recent|recent|new|this|current|just\s+added)\b/i;
const _KEEP_STOP = new Set(['the', 'and', 'one', 'ones', 'item', 'items', 'unit', 'units',
  'laptop', 'laptops', 'cart', 'my', 'a', 'an', 'in', 'there', 'please']);

export interface KeepResolution {
  isKeepClear: boolean;   // the query asked to CLEAR but KEEP something
  keepSkus: string[];     // SKUs to keep. isKeepClear && empty → intent clear but target ambiguous → ASK, never wipe
}

/**
 * Resolve "clear the cart but keep the latest / this one / the ThinkPad" → which SKUs to KEEP.
 *
 * The live bug: "clear the cart but keep the latest unit" has no "old/previous" word, so it missed the
 * scoped-clear and fell through to the FULL clear — wiping the item the buyer explicitly asked to keep.
 * This detects the keep intent and resolves the target: "latest/new/last/this" → the most-recently-added
 * item (this-session additions preferred, else the last cart line); a named product → distinctive-token
 * match. When the intent is clear but the target can't be resolved, returns isKeepClear=true with an EMPTY
 * keep set so the caller ASKS which to keep — it must NOT fall through to a full wipe. Pure + testable.
 */
export function keepAfterClear(query: string, items: CartLike[], initialSkus: string[] | null): KeepResolution {
  const q = String(query || '');
  const isKeepClear = _CLEAR_VERB.test(q) && _KEEP_CUE.test(q) && (_CART_OBJ.test(q) || _LATEST.test(q));
  if (!isKeepClear || !items || items.length === 0) return { isKeepClear, keepSkus: [] };

  const m = /\b(?:keep|except|but\s+keep|leave|save|apart\s+from|other\s+than)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:one|ones|item|items|unit|units|in\s+(?:my\s+)?cart|there|please|thanks?))?[.?!]*\s*$/i.exec(q);
  const obj = (m ? m[1] : '').trim().toLowerCase();

  // "latest / new / last / this" (or no explicit object) → the most-recently-added item
  if (!obj || _LATEST.test(obj)) {
    const init = new Set((initialSkus || []).map(String));
    const thisSession = items.filter((i) => !init.has(String(i.sku)));
    const pick = thisSession.length ? thisSession : items;
    return { isKeepClear, keepSkus: [String(pick[pick.length - 1].sku)] };   // last = most recent (add-order)
  }

  // a named product → keep the cart line whose name shares the most distinctive tokens
  const toks = obj.split(/[^a-z0-9]+/i).filter((t) => t.length >= 3 && !_KEEP_STOP.has(t.toLowerCase()));
  if (!toks.length) return { isKeepClear, keepSkus: [] };   // ambiguous → ASK
  const scored = items
    .map((i) => ({ sku: String(i.sku), hits: toks.filter((t) => String(i.name || i.sku || '').toLowerCase().includes(t.toLowerCase())).length }))
    .filter((x) => x.hits > 0)
    .sort((a, b) => b.hits - a.hits);
  return { isKeepClear, keepSkus: scored.length ? [scored[0].sku] : [] };
}
