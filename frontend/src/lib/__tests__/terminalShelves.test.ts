import { describe, expect, it } from 'vitest';
import { terminalShelves } from '../terminalShelves';

describe('terminal shelf authority', () => {
  const shelves = { schema_version: 'product-shelves-v1', shelves: [] };
  it('clears missing shelves instead of retaining an earlier projection', () => {
    expect(terminalShelves({ catalog_authority: 'permitted' })).toBeNull();
  });
  it('clears an authority downgrade even if the response carries old shelves', () => {
    expect(terminalShelves({ catalog_authority: 'blocked', product_shelves: shelves })).toBeNull();
    expect(terminalShelves({ research_outcome: { catalog_authority: 'blocked' }, product_shelves: shelves })).toBeNull();
  });
  it('retains explicitly permitted provisional exploration', () => {
    expect(terminalShelves({ catalog_authority: 'provisional', product_shelves: shelves })).toBe(shelves);
  });
});
