// PII / payment-data detection for the buyer chat input — pure, no React/DOM deps.
// Extracted from App.tsx so the security-sensitive logic is unit-tested in isolation.
// detectPII returns a {type, advice} the UI surfaces to steer the user to a safe channel,
// or null when nothing sensitive was found.

export type PIIMatch = { type: string; advice: string } | null;

export function luhnCheck(num: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = num.length - 1; i >= 0; i--) {
    let n = parseInt(num[i], 10);
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

export function detectPII(text: string): PIIMatch {
  // Credit card pattern (13-19 digits with optional spaces/dashes)
  const cardMatch = text.match(/\b(?:\d[ -]*?){13,19}\b/);
  if (cardMatch) {
    const digits = cardMatch[0].replace(/\D/g, '');
    if (digits.length >= 13 && digits.length <= 19) {
      // If it's a real-looking PAN (passes Luhn), block immediately.
      if (luhnCheck(digits)) {
        return {
          type: 'credit card number',
          advice: 'Never share payment card details in chat. Use our secure checkout instead.'
        };
      }

      // Demo/real-world: users often paste fake/test numbers that fail Luhn.
      // If strong card context is present (keywords or expiry), treat as PCI anyway.
      const hasCardHint = /\b(card|credit|debit|visa|mastercard|amex|american\s+express|discover)\b/i.test(text);
      const hasCvvHint = /\b(cvv|cvc|security\s*code|card\s*verification)\b/i.test(text);
      const hasExpiry = /\b(0[1-9]|1[0-2])\s*[/\-]\s*(\d{2}|\d{4})\b/.test(text);
      if (hasCardHint || hasCvvHint || hasExpiry) {
        return {
          type: 'payment card details',
          advice: 'Never share card numbers, expiry dates, or CVV in chat. Use secure checkout instead.'
        };
      }
    }
  }

  // SSN pattern
  if (/\b\d{3}-\d{2}-\d{4}\b/.test(text)) {
    return {
      type: 'Social Security Number',
      advice: 'SSNs should never be shared online. We will never ask for this information.'
    };
  }

  // Email in certain contexts (offering personal email)
  if (/\b(my email is|email me at|contact me at)\b/i.test(text) && /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/.test(text)) {
    return {
      type: 'email address',
      advice: 'For account inquiries, please use the Account section. We protect your privacy.'
    };
  }

  // Bank account numbers (8-17 digits preceded by keywords)
  if (/\b(account|routing|bank).{0,20}\d{8,17}\b/i.test(text)) {
    return {
      type: 'bank account information',
      advice: 'Never share banking details in chat. Contact our support team securely if needed.'
    };
  }

  return null;
}
