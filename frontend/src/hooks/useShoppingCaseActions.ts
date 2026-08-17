import { useCallback } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { AmbiguityExploration } from '../components/AmbiguityExplorationPanel';
import type { ProductShelfProjection, ShelfProduct } from '../components/ProductShelvesPanel';
import type { SupplierContinuation } from '../components/SupplierContinuationCard';
import type { ChatMessage } from '../conversationTypes';
import { apiErrorMessage } from '../lib/apiError';
import { selectProportionateAlternatives } from '../lib/proportionateAlternatives';
import { postShoppingCaseAction, shoppingCaseActionPath } from '../lib/shoppingCaseActions';


type ControllerInput = {
  uid: string;
  ambiguityExploration: AmbiguityExploration | null;
  productShelves: ProductShelfProjection | null;
  supplierContinuation: SupplierContinuation | null;
  setSupplierContinuation: Dispatch<SetStateAction<SupplierContinuation | null>>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  refreshCart: () => Promise<unknown>;
};


export function useShoppingCaseActions({
  uid, ambiguityExploration, productShelves, supplierContinuation,
  setSupplierContinuation, setMessages, refreshCart,
}: ControllerInput) {
  const proposeResearchedProduct = useCallback(async (item: ShelfProduct, quantity: number) => {
    if (!ambiguityExploration?.case_id) return;
    const freshQuantities = (item.availability || [])
      .filter((row) => row.freshness_status === 'fresh' && row.quantity != null
        && ['in_stock', 'available'].includes(row.status))
      .map((row) => Number(row.quantity || 0));
    const availabilityKnown = freshQuantities.length > 0 || (item.availability || []).some(
      (row) => row.freshness_status === 'fresh'
        && (row.quantity === 0 || ['sold_out', 'built_to_order', 'at_supplier'].includes(row.status)),
    );
    const availableNow = availabilityKnown
      ? freshQuantities.reduce((sum, value) => sum + value, 0) : null;
    if (availableNow == null || quantity > availableNow) {
      const alternatives = productShelves?.shelves
        .flatMap((shelf) => [...shelf.initial, ...shelf.next_page]) || [];
      const substitute = alternatives.find((candidate) => (
        candidate.product.sku !== item.product.sku
        && candidate.fit_status !== 'failed'
        && candidate.product.form_factor === item.product.form_factor
        && !(candidate.misses || []).length
        && candidate.price_cents <= item.price_cents
      ));
      setSupplierContinuation({
        caseId: ambiguityExploration.case_id,
        preferredSku: item.product.sku,
        preferredTitle: item.title,
        substituteSku: substitute?.product.sku,
        requestedQuantity: quantity,
        unitPriceCents: item.price_cents,
        currency: item.currency || 'AUD',
        availableNow,
        revision: Number(ambiguityExploration.interpretation_job?.case_revision || 1),
        deadlineDays: 10,
        choices: [],
        selectionKey: `portfolio-select-${crypto.randomUUID()}`,
        confirmationKey: `portfolio-confirm-${crypto.randomUUID()}`,
        status: 'review',
        proportionateAlternatives: selectProportionateAlternatives(item, alternatives),
      });
      return;
    }
    const sku = item.product.sku;
    const action = await postShoppingCaseAction(
      shoppingCaseActionPath.cartProposal(ambiguityExploration.case_id), { uid, sku, quantity },
    );
    const payload = action.payload;
    if (!action.ok) {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: String(payload?.detail?.message || payload?.detail?.code || payload?.detail
          || 'Cart proposal failed.'),
        timestamp: new Date(),
      }]);
      return;
    }
    setMessages((current) => [...current, {
      role: 'assistant',
      content: `I prepared a case-bound change for ${quantity} × ${sku}. Nothing has changed yet; confirm the plan below. Numeric availability is not attested, so any shortfall remains supplier-sourced.`,
      timestamp: new Date(),
      cartConfirm: { planId: payload.plan_id, ops: payload.ops, expiresAt: payload.expires_at },
    }]);
  }, [ambiguityExploration, productShelves, setMessages, setSupplierContinuation, uid]);

  const requestPortfolioNarrationPreview = useCallback(async (
    projection: NonNullable<ProductShelfProjection['narration_projection']>,
  ) => {
    if (!ambiguityExploration?.case_id) {
      return { text: projection.shelf_summary, renderer: 'deterministic', status: 'no_case', fallback_reason: 'no_case' };
    }
    const action = await postShoppingCaseAction(
      shoppingCaseActionPath.narrationPreview(ambiguityExploration.case_id), { uid, projection },
    );
    if (!action.ok) {
      return {
        text: projection.shelf_summary, renderer: 'deterministic', status: 'request_failed',
        fallback_reason: apiErrorMessage(action.payload, 'preview request failed'),
      };
    }
    return action.payload;
  }, [ambiguityExploration, uid]);

  const assessSupplierContinuation = useCallback(async (deadlineDays: number) => {
    if (!supplierContinuation) return;
    const action = await postShoppingCaseAction(
      shoppingCaseActionPath.fulfilmentOptions(supplierContinuation.caseId), {
        uid, requested_quantity: supplierContinuation.requestedQuantity,
        available_now: supplierContinuation.availableNow ?? 0,
        known_lead_time_days: 8, deadline_days: deadlineDays,
        has_next_best: Boolean(supplierContinuation.substituteSku),
        has_architecture_alternative: true,
      },
    );
    if (!action.ok) {
      setSupplierContinuation((current) => current
        ? { ...current, error: apiErrorMessage(action.payload, 'Fulfilment assessment failed.') }
        : current);
      return;
    }
    setSupplierContinuation((current) => current ? {
      ...current, deadlineDays, choices: action.payload?.choices || [], error: undefined,
    } : current);
  }, [setSupplierContinuation, supplierContinuation, uid]);

  const selectSupplierContinuation = useCallback(async (choiceId: string) => {
    if (!supplierContinuation) return;
    if (choiceId === 'alternative_architecture') {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: 'I kept the preferred laptop visible and expanded the architecture-specific shelves. Compare fixed workstation, mobile workstation and hosted alternatives before selecting a commercial path.',
        timestamp: new Date(),
      }]);
      return;
    }
    if (choiceId === 'relax_constraint') {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: 'Tell me which degree of freedom to change: quantity, delivery date, budget or a workload requirement. Nothing has changed yet.',
        timestamp: new Date(),
      }]);
      return;
    }
    const choice = choiceId === 'next_best_now' ? 'next_best_now' : choiceId;
    setSupplierContinuation((current) => current ? { ...current, status: 'selecting' } : current);
    const action = await postShoppingCaseAction(
      shoppingCaseActionPath.fulfilmentSelection(supplierContinuation.caseId), {
        uid, expected_revision: supplierContinuation.revision ?? 0, choice,
        preferred_sku: supplierContinuation.preferredSku,
        substitute_sku: supplierContinuation.substituteSku,
        requested_quantity: supplierContinuation.requestedQuantity,
        available_now: supplierContinuation.availableNow ?? 0,
        deadline_days: supplierContinuation.deadlineDays,
      }, { idempotencyKey: supplierContinuation.selectionKey },
    );
    if (!action.ok) {
      setSupplierContinuation((current) => current ? {
        ...current, status: 'review', error: apiErrorMessage(action.payload, 'Supplier fixture failed.'),
      } : current);
      return;
    }
    setSupplierContinuation((current) => current ? {
      ...current, selectedChoice: choice, selectionId: action.payload.selection_id,
      revision: action.payload.revision, offers: action.payload.offers || [],
      status: 'offers', error: undefined,
    } : current);
  }, [setMessages, setSupplierContinuation, supplierContinuation, uid]);

  const confirmSupplierContinuation = useCallback(async () => {
    if (!supplierContinuation?.selectionId || supplierContinuation.revision == null) return;
    const offer = supplierContinuation.offers?.find(
      (row) => row.offer_id === supplierContinuation.selectedOfferId,
    );
    setSupplierContinuation((current) => current ? { ...current, status: 'confirming' } : current);
    const action = await postShoppingCaseAction(
      shoppingCaseActionPath.confirmFulfilment(
        supplierContinuation.caseId, supplierContinuation.selectionId,
      ), {
        uid, expected_revision: supplierContinuation.revision,
        selected_offer_id: supplierContinuation.selectedOfferId || null,
        substitution_authorized: offer?.relationship === 'compatible_substitute',
      }, { idempotencyKey: supplierContinuation.confirmationKey },
    );
    if (!action.ok) {
      setSupplierContinuation((current) => current ? {
        ...current, status: 'offers', error: apiErrorMessage(action.payload, 'Cart confirmation failed.'),
      } : current);
      return;
    }
    await refreshCart();
    setSupplierContinuation((current) => current ? { ...current, status: 'applied', error: undefined } : current);
    setMessages((current) => [...current, {
      role: 'assistant',
      content: `Applied the explicitly confirmed fulfilment selection: ${action.payload.confirmed_quantity} × ${action.payload.confirmed_sku}. No real supplier was contacted.`,
      timestamp: new Date(),
    }]);
  }, [refreshCart, setMessages, setSupplierContinuation, supplierContinuation, uid]);

  return {
    assessSupplierContinuation,
    confirmSupplierContinuation,
    proposeResearchedProduct,
    requestPortfolioNarrationPreview,
    selectSupplierContinuation,
  };
}
