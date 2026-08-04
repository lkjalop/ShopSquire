import { describe, expect, it } from 'vitest';
import { detectPII, luhnCheck } from '../pii';

describe('luhnCheck', () => {
  it('accepts a valid PAN and rejects a transposed one', () => {
    expect(luhnCheck('4242424242424242')).toBe(true); // canonical Stripe test Visa
    expect(luhnCheck('4242424242424241')).toBe(false);
  });
});

describe('detectPII', () => {
  it('blocks a Luhn-valid card number immediately', () => {
    const m = detectPII('please charge 4242 4242 4242 4242');
    expect(m?.type).toBe('credit card number');
  });

  it('blocks a Luhn-invalid number when card context is present (demo/test PANs)', () => {
    const m = detectPII('my visa card is 1234 5678 9012 3456 exp 04/27');
    expect(m?.type).toBe('payment card details');
  });

  it('does not flag a bare long number with no card context', () => {
    // 16 zeros fail Luhn and there is no card/expiry/cvv hint -> not PII
    expect(detectPII('order reference 0000 0000 0000 0001 shipped')).toBeNull();
  });

  it('flags SSN, offered email, and bank-account context', () => {
    expect(detectPII('my ssn is 123-45-6789')?.type).toBe('Social Security Number');
    expect(detectPII('email me at jane@example.com')?.type).toBe('email address');
    expect(detectPII('my bank account 12345678901 routing')?.type).toBe('bank account information');
  });

  it('returns null for an ordinary shopping message', () => {
    expect(detectPII('show me gaming laptops under $1500')).toBeNull();
  });
});
