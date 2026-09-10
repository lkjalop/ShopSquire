import type { ProductShelfProjection } from '../components/ProductShelvesPanel';

/** Missing or blocked terminal projections replace, never inherit, old shelves. */
export function terminalShelves(terminal: {
  catalog_authority?: string;
  research_outcome?: { catalog_authority?: string } | null;
  product_shelves?: unknown;
}): ProductShelfProjection | null {
  if (terminal.catalog_authority === 'blocked'
      || terminal.research_outcome?.catalog_authority === 'blocked') return null;
  const shelves = terminal.product_shelves as ProductShelfProjection | undefined;
  return shelves?.schema_version === 'product-shelves-v1' ? shelves : null;
}
