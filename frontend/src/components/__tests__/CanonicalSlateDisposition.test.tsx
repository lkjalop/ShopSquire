import fs from 'node:fs';
import path from 'node:path';

describe('canonical recommendation slate disposition', () => {
  it('clears stale products when the backend marks an empty slate authoritative', () => {
    const app = fs.readFileSync(path.resolve(__dirname, '..', '..', 'App.tsx'), 'utf8');

    expect(app).toContain("slateDisposition === 'clear'");
    expect(app).toContain('setDisplayProducts([])');
    expect(app).toContain("switchRightPanelMode('none')");
  });
});
