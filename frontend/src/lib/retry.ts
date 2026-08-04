/**
 * Bounded retry for best-effort writes that can fail transiently (e.g. a SQLite write lock during a
 * multi-case commit burst — observed live: one of two supplier cases stuck uncommitted, its RFQ never
 * drafted, needing a manual re-commit). One retry after a short delay converts that transient into a
 * success without hammering the backend. Pure + injectable so it's unit-testable without timers.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts?: { attempts?: number; delayMs?: number; sleep?: (ms: number) => Promise<void> },
): Promise<T> {
  const attempts = Math.max(1, opts?.attempts ?? 2);
  const delayMs = opts?.delayMs ?? 400;
  const sleep = opts?.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      lastErr = e;
      if (i < attempts - 1) await sleep(delayMs * (i + 1));   // linear backoff: 400ms, 800ms, …
    }
  }
  throw lastErr;
}
