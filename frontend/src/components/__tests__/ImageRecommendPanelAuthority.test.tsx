import fs from 'node:fs';
import path from 'node:path';

describe('Image recommendation authority boundary', () => {
  it('keeps independent recommendation authority out of the image renderer', () => {
    const srcRoot = path.resolve(__dirname, '..', '..');
    const files: string[] = [];

    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (/\.(ts|tsx)$/.test(entry.name) && !full.includes('__tests__')) files.push(full);
      }
    };
    walk(srcRoot);

    const offenders = files.filter(file =>
      /allowLegacySuggest\s*=\s*\{?\s*true\s*\}?/.test(fs.readFileSync(file, 'utf8')),
    );
    expect(offenders).toEqual([]);

    const panel = fs.readFileSync(path.resolve(__dirname, '..', 'ImageRecommendPanel.tsx'), 'utf8');
    expect(panel).not.toMatch(/allowLegacySuggest\??:/);
    expect(panel).not.toContain('/api/v1/recommend/suggest');
    expect(panel).not.toContain('VITE_ENABLE_LEGACY_IMAGE_SUGGEST_ROLLBACK');
    // The independent recommendation path is fully EXCISED, not merely neutralized:
    // no fetchSuggest function/call sites and no local fallback catalogue remain.
    expect(panel).not.toContain('fetchSuggest');
    expect(panel).not.toContain('LOCAL_FAST_FALLBACK_PRODUCTS');
  });
});
