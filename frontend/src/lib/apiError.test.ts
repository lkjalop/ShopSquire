import { describe, expect, it } from 'vitest';

import { apiErrorMessage } from './apiError';

describe('apiErrorMessage', () => {
  it('never renders structured validation details as object coercion', () => {
    expect(apiErrorMessage({ detail: [{ msg: 'Field required' }] }, 'failed')).toBe('Field required');
    expect(apiErrorMessage({ detail: { code: 'stale_revision' } }, 'failed')).toBe('stale revision');
    expect(apiErrorMessage({ detail: { available: 3 } }, 'failed')).toBe('{"available":3}');
  });
});
