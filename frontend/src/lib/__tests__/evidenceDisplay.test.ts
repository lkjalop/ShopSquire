import { describe, it, expect } from 'vitest';
import { evidenceRows, citationChips, legMeta } from '../evidenceDisplay';

const EV = {
  selected: ['availability', 'market', 'web'],
  legs: {
    market: { source: 'market_intelligence', found: true, summary: 'undercut on 2 SKUs' },
    availability: { source: 'inventory', found: true, summary: '9 products, 400 units' },
    web: { source: 'external_web', found: true, summary: 'VRAM guidance…' },
  },
  citations: [
    { source: 'market_intelligence', summary: 'undercut on 2 SKUs' },
    { source: 'inventory', summary: '9 products' },
    { source: 'external_web', summary: 'VRAM guidance…' },
  ],
  ms: 32,
};

describe('evidenceRows', () => {
  it('orders trusted store records before external evidence (the hierarchy IS the layout)', () => {
    const rows = evidenceRows(EV as any);
    expect(rows.map(r => r.trusted)).toEqual([true, true, false]);
    expect(rows[rows.length - 1].label).toBe('External web');
  });
  it('empty/absent evidence renders nothing', () => {
    expect(evidenceRows(null)).toEqual([]);
    expect(evidenceRows({} as any)).toEqual([]);
  });
  it('a failed leg keeps its error visible (never silently dropped)', () => {
    const rows = evidenceRows({ legs: { market: { source: 'market_intelligence', found: false, error: 'leg_timeout>2.5s' } } } as any);
    expect(rows[0].error).toContain('leg_timeout');
  });
});

describe('citationChips', () => {
  it('maps citations to labeled chips with trust flags', () => {
    const chips = citationChips(EV as any);
    expect(chips.map(c => c.label)).toContain('Market intelligence');
    expect(chips.find(c => c.key === 'external_web')?.trusted).toBe(false);
  });
  it('unknown source falls back to a generic chip, never crashes', () => {
    expect(legMeta('mystery_source').label).toBe('mystery_source');
  });
});
