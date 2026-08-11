import { describe, expect, it } from 'vitest';

import { isUnusableImageEvidence } from './imageEvidenceAuthority';

describe('image evidence authority', () => {
  it.each(['pending', 'degraded', 'quarantined', 'superseded'])(
    'blocks the %s artifact state',
    (state) => {
      expect(isUnusableImageEvidence({ artifact: { state } })).toBe(true);
    },
  );

  it('blocks client timeout hints, upload failures, and explicit authority denial', () => {
    expect(isUnusableImageEvidence({ provider: 'client_fast_boundary' })).toBe(true);
    expect(isUnusableImageEvidence({ _upload_error: 'mime_mismatch' })).toBe(true);
    expect(isUnusableImageEvidence({ security: { commercial_authority: 'blocked' } })).toBe(true);
  });

  it('allows only a completed result without a blocking authority signal', () => {
    expect(isUnusableImageEvidence({
      artifact: { state: 'clean' },
      security: { commercial_authority: 'read_only' },
    })).toBe(false);
  });
});
