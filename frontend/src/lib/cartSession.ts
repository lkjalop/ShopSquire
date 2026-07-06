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
