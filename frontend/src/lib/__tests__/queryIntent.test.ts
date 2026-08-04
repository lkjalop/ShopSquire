import { describe, expect, it } from 'vitest';
import {
  detectCVIssueType,
  detectPanelMode,
  hasDamageSignal,
  isCartUpsellIntentQuery,
  isComplaintIntent,
  isShoppingIntentQuery,
  requiresExternalResearchConsent,
  shouldRouteToComplaint,
} from '../queryIntent';

describe('shouldRouteToComplaint (chat-firing misroute guard)', () => {
  const base = {
    mode: 'grid' as const, complaintIntent: false, explicitComplaintIntent: false,
    shoppingIntent: false, damageSignal: false, hasImages: false,
    explicitVisualIntent: false, hasImageContext: false,
  };
  it('keeps a shopping query that merely mentions "return" on the recommendations path', () => {
    // "i need 15 laptops, easy return?" → weak complaint word + shopping intent → NOT complaint (→ /chat)
    expect(shouldRouteToComplaint({ ...base, shoppingIntent: true, complaintIntent: true,
      explicitComplaintIntent: true })).toBe(false);
  });
  it('routes a genuine damage report to complaint even with product words', () => {
    expect(shouldRouteToComplaint({ ...base, shoppingIntent: true, damageSignal: true })).toBe(true);
  });
  it('routes a non-shopping return request to complaint', () => {
    expect(shouldRouteToComplaint({ ...base, complaintIntent: true })).toBe(true);
  });
  it('does not let a broad return-word hint hijack a policy question', () => {
    expect(shouldRouteToComplaint({
      ...base,
      mode: 'cv',
      explicitComplaintIntent: true,
      complaintIntent: false,
    })).toBe(false);
  });
  it('never routes image/visual turns here', () => {
    expect(shouldRouteToComplaint({ ...base, damageSignal: true, hasImages: true })).toBe(false);
    expect(shouldRouteToComplaint({ ...base, complaintIntent: true, explicitVisualIntent: true })).toBe(false);
  });
});

describe('hasDamageSignal', () => {
  it('detects post-purchase damage/defect words', () => {
    expect(hasDamageSignal('my laptop arrived broken')).toBe(true);
    expect(hasDamageSignal('the screen is cracked')).toBe(true);
  });
  it('is false for a pre-purchase return question', () => {
    expect(hasDamageSignal('what is your return window before I buy 15 laptops')).toBe(false);
  });
});

describe('isShoppingIntentQuery', () => {
  it('recognises product/budget/brand language', () => {
    expect(isShoppingIntentQuery('show me gaming laptops under $1500')).toBe(true);
    expect(isShoppingIntentQuery('dell vs hp')).toBe(true);
  });
  it('is false for pure support/policy text', () => {
    expect(isShoppingIntentQuery('what is your returns policy')).toBe(false);
  });
});

describe('detectPanelMode', () => {
  it('routes compare / specs / cv / faq / grid / none', () => {
    expect(detectPanelMode('compare the XPS vs the MacBook')).toBe('compare');
    expect(detectPanelMode('show me the detailed specs')).toBe('list');
    expect(detectPanelMode('my laptop arrived damaged, refund')).toBe('cv');
    expect(detectPanelMode('how do i track shipping')).toBe('faq');
    expect(detectPanelMode('find me a student laptop')).toBe('grid');
    expect(detectPanelMode('hello there')).toBe('none');
  });
  it('prefers shopping grid over faq when both could match', () => {
    // "warranty" is an faq trigger but a shopping query keeps grid
    expect(detectPanelMode('cheap laptop with good warranty')).toBe('grid');
  });
  it('uses the faq panel for a returns-policy question', () => {
    expect(detectPanelMode('what is your returns policy')).toBe('faq');
  });
});

describe('isCartUpsellIntentQuery', () => {
  it('detects accessory / bundle / "what else" intent', () => {
    expect(isCartUpsellIntentQuery('what else should i buy with this')).toBe(true);
    expect(isCartUpsellIntentQuery('any compatible accessories?')).toBe(true);
    expect(isCartUpsellIntentQuery('show me laptops')).toBe(false);
  });
});

describe('requiresExternalResearchConsent', () => {
  it('recognises explicit external-research requests', () => {
    expect(requiresExternalResearchConsent('search online for Black Myth Wukong requirements')).toBe(true);
    expect(requiresExternalResearchConsent('look it up on the web')).toBe(true);
    expect(requiresExternalResearchConsent('check the internet for current specs')).toBe(true);
  });

  it('does not treat ordinary catalog search as external consent', () => {
    expect(requiresExternalResearchConsent('search for a gaming laptop under AUD 3000')).toBe(false);
    expect(requiresExternalResearchConsent('show me Black Myth Wukong laptops')).toBe(false);
  });
});

describe('detectCVIssueType', () => {
  it('classifies warranty / return / refund (default)', () => {
    expect(detectCVIssueType('warranty claim please')).toBe('warranty');
    expect(detectCVIssueType('i want to send back this item')).toBe('return');
    expect(detectCVIssueType('this is broken')).toBe('refund');
  });
});

describe('isComplaintIntent', () => {
  it('is true for damage+action and action-without-policy', () => {
    expect(isComplaintIntent('my laptop is damaged, i want a refund')).toBe(true);
    expect(isComplaintIntent('i want to return this')).toBe(true);
  });
  it('is false for policy-only questions', () => {
    expect(isComplaintIntent('what is your return policy')).toBe(false);
    expect(isComplaintIntent('how do i start a warranty process')).toBe(false);
  });
});
