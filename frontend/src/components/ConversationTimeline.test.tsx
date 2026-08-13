import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ConversationTimeline from './ConversationTimeline';

const classes = new Proxy({}, { get: (_target, key) => String(key) }) as Record<string, string>;
const callbacks = {
  onQuickAction: vi.fn(), onNqeOption: vi.fn(), onDisambiguation: vi.fn(),
  onWebConsent: vi.fn(), onOpenEvidence: vi.fn(), onUndoClear: vi.fn(),
  onUndoServer: vi.fn(), onConfirmCart: vi.fn(), onDismissCart: vi.fn(),
  onAcceptRequirements: vi.fn(), onAffordabilityChoice: vi.fn(),
};

describe('ConversationTimeline', () => {
  it('renders evidence-bound conversation controls through callbacks', () => {
    const message: any = {
      role: 'assistant', content: 'A **conditional** recommendation.', timestamp: new Date(),
      webConsentPrompt: { query: 'official solver requirements' },
      nextQuestions: [{ id: 'q1', text: 'Which solver?', options: [{ id: 'o1', label: 'Solver A' }] }],
      evidence: { citations: [{ source_type: 'official', title: 'Publisher manual', url: 'https://example.test/manual' }] },
    };
    render(<ConversationTimeline messages={[message]} classNames={classes}
      showDebugBadges={false} cartItems={[]} {...callbacks} />);
    expect(screen.getByText('conditional').tagName).toBe('STRONG');
    fireEvent.click(screen.getByRole('button', { name: /Check approved sources/ }));
    expect(callbacks.onWebConsent).toHaveBeenCalledWith(message, true);
    fireEvent.click(screen.getByRole('button', { name: 'Solver A' }));
    expect(callbacks.onNqeOption).toHaveBeenCalled();
  });
});
