import { describe, expect, it } from 'vitest';
import { procurementActionMessage } from './actionError';

describe('procurementActionMessage (409-replay UX)', () => {
  it('treats an idempotent replay as a calm refresh', () => {
    const m = procurementActionMessage({ status: 409, detail: 'idempotent_replay' });
    expect(m.calm).toBe(true);
    expect(m.message).toMatch(/already applied/i);
  });
  it('treats a state conflict (illegal/terminal) as calm', () => {
    expect(procurementActionMessage({ status: 409, detail: 'illegal_transition' }).calm).toBe(true);
    expect(procurementActionMessage({ status: 409, detail: 'terminal_state' }).message).toMatch(/moved past/i);
  });
  it('treats a 409 rate limit as a calm retry hint', () => {
    expect(procurementActionMessage({ status: 409, detail: 'confirm_cart_rate_limited' }).message).toMatch(/retry/i);
  });
  it('surfaces non-409 errors as real errors', () => {
    const m = procurementActionMessage({ status: 500, message: 'boom' });
    expect(m.calm).toBe(false);
    expect(m.message).toBe('boom');
  });
});
