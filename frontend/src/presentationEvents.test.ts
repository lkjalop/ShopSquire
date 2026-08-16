import { describe, expect, it } from 'vitest';
import { createPresentationEventDispatcher, type PresentationEventSinks } from './presentationEvents';
import type { ChatMessage } from './conversationTypes';

function sink<T>(state: { value: T }) {
  return (update: T | ((current: T) => T)) => {
    state.value = typeof update === 'function'
      ? (update as (current: T) => T)(state.value)
      : update;
  };
}

describe('storefront presentation events', () => {
  it('projects typed research state without granting action authority', () => {
    const messages = { value: [] as ChatMessage[] };
    const shelves = { value: null as any };
    const ambiguity = { value: { case_id: 'case-1', status: 'provisional' } as any };
    const active = { value: null as any };
    const supplier = { value: null as any };
    const dispatch = createPresentationEventDispatcher({
      setMessages: sink(messages),
      setProductShelves: sink(shelves),
      setAmbiguityExploration: sink(ambiguity),
      setActiveShoppingCase: sink(active),
      setSupplierContinuation: sink(supplier),
    } satisfies PresentationEventSinks);

    dispatch({
      type: 'shopping_case.ambiguity.patched', source: 'research',
      authority: 'presentation_only', patch: { status: 'researched' },
    });
    dispatch({
      type: 'conversation.message.appended', source: 'research',
      authority: 'presentation_only',
      message: { role: 'assistant', content: 'Research completed.', timestamp: new Date(0) },
    });

    expect(ambiguity.value.status).toBe('researched');
    expect(messages.value.map((item) => item.content)).toEqual(['Research completed.']);
  });
});
