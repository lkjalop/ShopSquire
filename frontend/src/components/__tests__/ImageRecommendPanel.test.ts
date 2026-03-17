/**
 * frontend/src/components/__tests__/ImageRecommendPanel.test.ts
 * Unit tests for computeTrustLevel — covers steg + all trust branches.
 */
import { describe, it, expect } from 'vitest';
import { computeTrustLevel } from '../ImageRecommendPanel';

const clean = () => ({});

describe('computeTrustLevel', () => {
  // ── green ────────────────────────────────────────────────────────────────
  it('returns green for a clean image with no suspicious signals', () => {
    expect(computeTrustLevel(clean(), 0)).toBe('green');
  });

  it('returns green with 1 session-suspicious count and no signals', () => {
    expect(computeTrustLevel(clean(), 1)).toBe('green');
  });

  // ── yellow ───────────────────────────────────────────────────────────────
  it('returns yellow when qr_code_detected only', () => {
    expect(computeTrustLevel({ qr_code_detected: true }, 0)).toBe('yellow');
  });

  // ── orange ───────────────────────────────────────────────────────────────
  it('returns orange when qr_external_url_detected', () => {
    expect(computeTrustLevel({ qr_external_url_detected: true }, 0)).toBe('orange');
  });

  it('returns orange when manipulation_detected', () => {
    expect(computeTrustLevel({ manipulation_detected: true }, 0)).toBe('orange');
  });

  it('returns orange when steg_suspicious (the new steg fix)', () => {
    expect(computeTrustLevel({ steg_suspicious: true }, 0)).toBe('orange');
  });

  it('returns orange when steg_suspicious even with only 1 session-suspicious', () => {
    expect(computeTrustLevel({ steg_suspicious: true }, 1)).toBe('orange');
  });

  it('returns orange when sessionSuspicious >= 2 even without signals', () => {
    expect(computeTrustLevel(clean(), 2)).toBe('orange');
  });

  it('returns orange when steg_suspicious + qr_code_detected (steg takes precedence over yellow)', () => {
    expect(computeTrustLevel({ steg_suspicious: true, qr_code_detected: true }, 0)).toBe('orange');
  });

  // ── red ──────────────────────────────────────────────────────────────────
  it('returns red when qr_prompt_injection', () => {
    expect(computeTrustLevel({ qr_prompt_injection: true }, 0)).toBe('red');
  });

  it('returns red when sessionSuspicious >= 3 with clean signals', () => {
    expect(computeTrustLevel(clean(), 3)).toBe('red');
  });

  it('returns red when sessionSuspicious >= 3 even with steg (red > orange)', () => {
    expect(computeTrustLevel({ steg_suspicious: true }, 3)).toBe('red');
  });

  it('steg_suspicious false does not raise level', () => {
    expect(computeTrustLevel({ steg_suspicious: false }, 0)).toBe('green');
  });
});
