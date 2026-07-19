/**
 * frontend/src/components/__tests__/ImageRecommendPanel.test.ts
 * Unit tests for computeTrustLevel — covers steg + all trust branches.
 */
import { describe, it, expect } from 'vitest';
import { buildProsNote, computeTrustLevel, shouldUseFastPath, isProofRelevant, normalizeUseCaseFit } from '../ImageRecommendPanel';

const clean = () => ({});

describe('isProofRelevant (proof-of-purchase CTA gating)', () => {
  const g = (over: any = {}) => ({ trustLevel: 'green', securityNote: '', products: [], source: '', icon: '', friendlyBrand: '', summary: '', ...over } as any);

  it('hides proof CTAs during normal shopping / visual search', () => {
    expect(isProofRelevant(g(), 'gaming laptop under $1800')).toBe(false);
    expect(isProofRelevant(g({ context: { intent_routing: { intent: 'visual_search' } } }), 'show me laptops')).toBe(false);
  });

  it('shows proof CTAs for repair/damage intent', () => {
    expect(isProofRelevant(g({ isRepairIntent: true }), 'my screen is cracked')).toBe(true);
  });

  it('shows proof CTAs when the query is warranty/return/refund/ownership', () => {
    expect(isProofRelevant(g(), 'I need a warranty claim for my laptop')).toBe(true);
    expect(isProofRelevant(g(), 'how do I return this for a refund?')).toBe(true);
    expect(isProofRelevant(g(), 'proof of purchase for my order')).toBe(true);
  });

  it('shows proof CTAs when the triage intent is proof-relevant', () => {
    expect(isProofRelevant(g({ context: { intent_routing: { intent: 'returns' } } }), '')).toBe(true);
  });
});

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

describe('shouldUseFastPath', () => {
  it('keeps fast path for plain visual search queries', () => {
    expect(shouldUseFastPath('show me gaming laptops')).toBe(true);
  });

  it('disables fast path for budget reasoning questions', () => {
    expect(shouldUseFastPath('im looking for a gaming laptop? is 1800 enough? or should i go higher? why?')).toBe(false);
  });
});

describe('normalizeUseCaseFit', () => {
  it('turns structured fit evidence into renderable buyer text', () => {
    expect(normalizeUseCaseFit({
      use_case: 'office_work', suitable: false, verdict: 'below recommended',
      gaps: ['gpu_vram_gb'], strengths: ['ram_gb'], overkill_score: 0,
    })).toBe('below recommended - gpu vram gb');
  });

  it('preserves string fit summaries and rejects unknown shapes', () => {
    expect(normalizeUseCaseFit('Good office fit')).toBe('Good office fit');
    expect(normalizeUseCaseFit(null)).toBeNull();
  });
});

describe('buildProsNote', () => {
  it('does not label generic integrated Radeon graphics as a discrete GPU', () => {
    expect(buildProsNote({ name: 'Office laptop', specs_summary: '16GB · Radeon Graphics' } as any, 'office work'))
      .toBe('16 GB RAM');
  });

  it('does label explicit Radeon RX and GeForce RTX models as discrete GPUs', () => {
    expect(buildProsNote({ name: 'Creator laptop', specs_summary: '16GB · Radeon RX 7700S' } as any, 'image generation'))
      .toContain('Discrete GPU');
    expect(buildProsNote({ name: 'Gaming laptop', specs_summary: '16GB · GeForce RTX 4060' } as any, 'gaming'))
      .toContain('Discrete GPU');
  });
});

describe('analysis availability is not a security verdict', () => {
  it('does not mark a fast-triage timeout as suspicious', () => {
    expect(computeTrustLevel({ fast_triage_timeout: true } as any, 0)).toBe('green');
  });
});
