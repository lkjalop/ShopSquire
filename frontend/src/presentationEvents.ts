import type { ChatMessage } from './conversationTypes';
import type { AmbiguityExploration } from './components/AmbiguityExplorationPanel';
import type { ProductShelfProjection } from './components/ProductShelvesPanel';
import type { SupplierContinuation } from './components/SupplierContinuationCard';
import type { ActiveShoppingCase } from './hooks/useShoppingCaseResearch';

type StateUpdate<T> = T | ((current: T) => T);
type StateSink<T> = (update: StateUpdate<T>) => void;

type PresentationMetadata = {
  source: 'chat' | 'research' | 'catalog' | 'supplier' | 'buyer_action';
  authority: 'presentation_only';
};

export type StorefrontPresentationEvent =
  | ({ type: 'conversation.message.appended'; message: ChatMessage } & PresentationMetadata)
  | ({ type: 'shopping_case.shelves.replaced'; shelves: ProductShelfProjection | null } & PresentationMetadata)
  | ({ type: 'shopping_case.ambiguity.replaced'; exploration: AmbiguityExploration | null } & PresentationMetadata)
  | ({ type: 'shopping_case.ambiguity.patched'; patch: Partial<AmbiguityExploration> } & PresentationMetadata)
  | ({ type: 'shopping_case.active.replaced'; shoppingCase: ActiveShoppingCase | null } & PresentationMetadata)
  | ({ type: 'supplier.continuation.replaced'; continuation: SupplierContinuation | null } & PresentationMetadata);

export type PresentationEventSinks = {
  setMessages: StateSink<ChatMessage[]>;
  setProductShelves: StateSink<ProductShelfProjection | null>;
  setAmbiguityExploration: StateSink<AmbiguityExploration | null>;
  setActiveShoppingCase: StateSink<ActiveShoppingCase | null>;
  setSupplierContinuation: StateSink<SupplierContinuation | null>;
};

/**
 * A typed presentation boundary, deliberately without network or commerce authority.
 * Async orchestration can emit an event; this dispatcher alone projects it into UI state.
 */
export function createPresentationEventDispatcher(sinks: PresentationEventSinks) {
  return (event: StorefrontPresentationEvent) => {
    if (event.authority !== 'presentation_only') return;
    switch (event.type) {
      case 'conversation.message.appended':
        sinks.setMessages((current) => [...current, event.message]);
        return;
      case 'shopping_case.shelves.replaced':
        sinks.setProductShelves(event.shelves);
        return;
      case 'shopping_case.ambiguity.replaced':
        sinks.setAmbiguityExploration(event.exploration);
        return;
      case 'shopping_case.ambiguity.patched':
        sinks.setAmbiguityExploration((current) => current ? { ...current, ...event.patch } : current);
        return;
      case 'shopping_case.active.replaced':
        sinks.setActiveShoppingCase(event.shoppingCase);
        return;
      case 'supplier.continuation.replaced':
        sinks.setSupplierContinuation(event.continuation);
    }
  };
}
