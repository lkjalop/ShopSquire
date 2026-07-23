import fs from 'node:fs';
import path from 'node:path';

describe('Image recommendation authority boundary', () => {
  it('keeps the legacy suggest rollback out of the component API', () => {
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
    expect(panel).toContain('VITE_ENABLE_LEGACY_IMAGE_SUGGEST_ROLLBACK');
  });
});
