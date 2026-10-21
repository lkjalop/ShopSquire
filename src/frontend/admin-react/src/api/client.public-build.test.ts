// @vitest-environment node
import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { expect, it } from 'vitest';

const execute = promisify(execFile);

it('keeps build-environment operator credentials out of published JavaScript', async () => {
  const output = await mkdtemp(join(tmpdir(), 'shopsquire-admin-public-build-'));
  const credential = `operator-build-canary-${randomUUID()}`;
  try {
    await execute(process.execPath, [
      resolve('node_modules/vite/bin/vite.js'), 'build', '--outDir', output,
    ], {
      cwd: process.cwd(),
      env: { ...process.env, VITE_API_KEY: credential, VITE_OWNER_API_KEY: '' },
      timeout: 45_000,
      maxBuffer: 2 * 1024 * 1024,
    });
    const assets = join(output, 'assets');
    const names = (await readdir(assets)).filter(name => name.endsWith('.js'));
    expect(names.length).toBeGreaterThan(0);
    const bundles = await Promise.all(names.map(name => readFile(join(assets, name), 'utf8')));
    // This positive control proves that the actual shared admin client was built.
    expect(bundles.some(bundle => bundle.includes('shopsquire_admin_api_key'))).toBe(true);
    expect(bundles.some(bundle => bundle.includes(credential))).toBe(false);
  } finally {
    await rm(output, { recursive: true, force: true });
  }
}, 60_000);
