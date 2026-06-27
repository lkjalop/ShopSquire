import { describe, expect, it } from 'vitest';
import {
  detectCVIssueType,
  detectPanelMode,
  isCartUpsellIntentQuery,
  isComplaintIntent,
  isShoppingIntentQuery,
} from '../queryIntent';

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
});

describe('isCartUpsellIntentQuery', () => {
  it('detects accessory / bundle / "what else" intent', () => {
    expect(isCartUpsellIntentQuery('what else should i buy with this')).toBe(true);
    expect(isCartUpsellIntentQuery('any compatible accessories?')).toBe(true);
    expect(isCartUpsellIntentQuery('show me laptops')).toBe(false);
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
