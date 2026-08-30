// Query-intent detectors for the buyer chat — pure string heuristics, no React/DOM deps.
// Extracted from App.tsx so the routing logic (which right-panel to show, complaint vs browse,
// upsell, CV issue type) is unit-tested in isolation. RightPanelMode lives here because
// detectPanelMode returns it.

export type RightPanelMode =
  | 'none' | 'grid' | 'list' | 'compare' | 'cv' | 'cart' | 'faq' | 'security' | 'visual_search' | 'image_context';

export function isShoppingIntentQuery(query: string): boolean {
  const q = String(query || '').toLowerCase();
  return /laptop|computer|price|under|below|above|budget|cheap|affordable|\$|show|find|search|gaming|macbook|dell|hp|asus|lenovo|msi|university|student|study/.test(q);
}

export function detectPanelMode(query: string): RightPanelMode {
  const q = query.toLowerCase();
  const shoppingIntent = isShoppingIntentQuery(q);
  // Compare triggers
  if (/compare|vs|versus|difference|which is better|pros.?cons|side.?by.?side|head.?to.?head/.test(q)) return 'compare';
  // Detailed/specs triggers
  if (/specs|specification|details|detailed|features|info|information|describe|tell me about|breakdown/.test(q)) return 'list';
  // FAQ triggers
  if (/faq|how do i|what is|shipping|warranty|policy|support/.test(q) && !shoppingIntent) return 'faq';
  // CV/return triggers (when images attached - handled separately)
  if (/return|complaint|damaged|broken|defective|refund|issue|problem/.test(q)) return 'cv';
  // Product search (default when products mentioned)
  if (shoppingIntent) return 'grid';
  return 'none';
}

export function isCartUpsellIntentQuery(query: string): boolean {
  const q = query.toLowerCase();
  return /add[\s-]?on|accessor(y|ies)|what else should i buy|what else should i get|compatible|bundle|extra \$?\d+|spend .* extra|upsell/i.test(q);
}

export function requiresExternalResearchConsent(query: string): boolean {
  const q = String(query || '');
  const researchVerb = /\b(?:search|check|look(?:\s+it)?\s+up|google|browse)\b/i;
  const externalTarget = /\b(?:the\s+)?(?:web|online|internet)\b/i;
  return researchVerb.test(q) && externalTarget.test(q);
}

/**
 * A title-bearing game request belongs on the governed chat/router path, where the
 * literal title can be identity-resolved. Sending it through the generic open-world
 * intake first duplicates model work and can erase the title into a generic workload.
 */
export function hasNamedGameWorkload(query: string): boolean {
  const text = String(query || '');
  const patterns = [
    /\b(?:is|would)\s+(?:aud\s*)?\$?\d[\d,]*(?:\.\d+)?\s+(?:enough|sufficient|acceptable|ok(?:ay)?|excessive|overkill|too\s+much)\s+for\s+(.{3,120}?)(?=[?.!,;]|$)/i,
    /\bplay\s+(?:the\s+)?(.{3,120}?)(?=[?.!,;]|\s+is\s+(?:aud\s*)?\$?\d|$)/i,
    /\bwhat\s+about\s+(.{3,120}?)(?=[?.!,;]|\s+is\s+(?:aud\s*)?\$?\d|$)/i,
    /\b(?:can|could|will)\s+(?:it|this(?:\s+laptop)?|that(?:\s+laptop)?|a\s+laptop|the\s+laptop)\s+(?:run|play)\s+(.{3,120}?)(?=[?.!,;]|$)/i,
    /\bi\s+want\s+(?:a\s+laptop\s+)?(?:that\s+can|to)\s+(?:run|play)\s+(.{3,120}?)(?=[?.!,;]|\s+is\s+(?:aud\s*)?\$?\d|$)/i,
    /\b(?:laptop|computer|pc)\s+for\s+(.{3,120}?)(?=[?.!,;]|\s+is\s+(?:aud\s*)?\$?\d|$)/i,
  ];
  const matchedIndex = patterns.findIndex((pattern) => pattern.test(text));
  const match = matchedIndex >= 0 ? text.match(patterns[matchedIndex]) : null;
  if (!match) return false;
  const title = String(match[1] || '')
    .replace(/^\s*(?:a|the|some)\s+/i, '')
    .trim();
  if (!title || /^(?:games?|gaming|online|locally|work|school|university|office|digital\s+twin(?:\s+simulations?)?)$/i.test(title)) return false;
  if (matchedIndex === patterns.length - 1) {
    const titleWords = title.match(/\b[A-Z][A-Za-z']+\b/g) || [];
    if (!/\d/.test(title) && titleWords.length < 2) return false;
  }
  return title.split(/\s+/).length >= 2;
}

export function detectCVIssueType(query: string): string {
  const q = query.toLowerCase();
  if (/warranty|under warranty|warranty claim|warranty repair|warranty coverage/.test(q)) return 'warranty';
  if (/return|send back|ship back/.test(q)) return 'return';
  return 'refund';
}

export function isComplaintIntent(query: string): boolean {
  const q = query.toLowerCase();
  const action = /return|refund|complaint/.test(q);
  const damage = /damaged|broken|defective|issue|problem/.test(q);
  const evidence = /photo|picture|image|upload|evidence/.test(q);
  const policyOnly = /policy|eligibility|warranty|how do i|steps|process/.test(q);
  if (damage && (action || evidence)) return true;
  if (action && !policyOnly) return true;
  return false;
}

// A genuine post-purchase damage/defect signal (not a pre-purchase "what's your return window?").
export function hasDamageSignal(query: string): boolean {
  return /\b(damaged|broken|defective|not working|stopped working|wrong item|faulty|cracked|dead on arrival|doa)\b/i
    .test(String(query || ''));
}

// Decide whether a buyer turn goes to the COMPLAINT/return orchestrator instead of product recommendations.
// The bug this fixes: a clear shopping query that merely mentions "return"/"refund" (a pre-purchase
// question) was routed to the complaint path → no /chat request fired, no recommendations. Rule: a genuine
// damage/defect signal always routes to complaint; otherwise a weak complaint word does NOT override a
// shopping-intent query. Image/visual turns are handled elsewhere, so they never route here.
export function shouldRouteToComplaint(opts: {
  mode: RightPanelMode; complaintIntent: boolean; explicitComplaintIntent: boolean;
  shoppingIntent: boolean; damageSignal: boolean; hasImages: boolean;
  explicitVisualIntent: boolean; hasImageContext: boolean;
}): boolean {
  if (opts.hasImages || opts.explicitVisualIntent || opts.hasImageContext) return false;
  if (opts.damageSignal) return true;  // real post-purchase issue → complaint, even with product words
  // `explicitComplaintIntent` is intentionally not authoritative here: it is a broad
  // image-context hint that also matches benign policy questions such as "return policy".
  return opts.complaintIntent && !opts.shoppingIntent;
}
