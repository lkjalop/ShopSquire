import { describe, it, expect } from 'vitest';
import { withRetry } from '../retry';

const noSleep = () => Promise.resolve();

describe('withRetry', () => {
  it('returns on first success without retrying', async () => {
    let calls = 0;
    const out = await withRetry(async () => { calls++; return 'ok'; }, { sleep: noSleep });
    expect(out).toBe('ok');
    expect(calls).toBe(1);
  });

  it('retries a transient failure and succeeds (the stuck-commit scenario)', async () => {
    let calls = 0;
    const out = await withRetry(async () => {
      calls++;
      if (calls === 1) throw new Error('database is locked');
      return 'committed';
    }, { sleep: noSleep });
    expect(out).toBe('committed');
    expect(calls).toBe(2);
  });

  it('throws the last error once attempts are exhausted', async () => {
    let calls = 0;
    await expect(withRetry(async () => { calls++; throw new Error(`fail ${calls}`); },
                           { attempts: 3, sleep: noSleep })).rejects.toThrow('fail 3');
    expect(calls).toBe(3);
  });

  it('backs off linearly between attempts', async () => {
    const waits: number[] = [];
    await expect(withRetry(async () => { throw new Error('x'); },
                           { attempts: 3, delayMs: 100, sleep: async (ms) => { waits.push(ms); } }))
      .rejects.toThrow();
    expect(waits).toEqual([100, 200]);   // no sleep after the final attempt
  });
});
