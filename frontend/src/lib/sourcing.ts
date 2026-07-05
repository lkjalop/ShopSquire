import type { ConfirmCartResult } from './api';

/**
 * Which procurement cases did a cart-sourcing confirm actually produce?
 *
 * The NEW cases live in DIFFERENT places depending on the path the backend took:
 *   • first confirm of an order  → top-level `cases`
 *   • SUPERSEDE (buyer amended)  → nested `created.cases` (the retired cases are in `superseded`)
 *
 * Reading only `cases` after a supersede would commit nothing and leave the Procurement tab on the STALE
 * order's RFQ — the wrong SKU/qty for the current cart. These pick the current cart's cases/count from
 * either shape. Pure + deterministic so it's unit-testable in isolation.
 */
export function sourcedCasesFrom(res: ConfirmCartResult | null | undefined): Array<{ case_id: string }> {
  return (res?.created?.cases as Array<{ case_id: string }> | undefined)
    || (res?.cases as Array<{ case_id: string }> | undefined)
    || [];
}

export function sourcedCaseCountFrom(res: ConfirmCartResult | null | undefined): number {
  return (res?.created?.case_count ?? res?.case_count) ?? 0;
}
