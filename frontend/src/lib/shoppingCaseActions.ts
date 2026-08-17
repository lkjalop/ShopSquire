import { apiUrl, safeJson } from './api';
import { csrfHeaders } from './csrf';


export type ShoppingCaseActionResult = {
  ok: boolean;
  status: number;
  payload: any;
};


export async function postShoppingCaseAction(
  path: string,
  body: Record<string, unknown>,
  options: { idempotencyKey?: string; signal?: AbortSignal } = {},
): Promise<ShoppingCaseActionResult> {
  const response = await fetch(apiUrl(path), {
    method: 'POST', credentials: 'include', signal: options.signal,
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
      ...(options.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : {}),
      ...csrfHeaders(),
    },
    body: JSON.stringify(body),
  });
  return { ok: response.ok, status: response.status, payload: await safeJson(response) };
}


export const shoppingCaseActionPath = {
  interpretation: () => '/api/v1/shopping-cases/interpretations',
  cartProposal: (caseId: string) => `/api/v1/shopping-cases/${encodeURIComponent(caseId)}/cart-proposals`,
  narrationPreview: (caseId: string) => `/api/v1/shopping-cases/${encodeURIComponent(caseId)}/narration-preview`,
  fulfilmentOptions: (caseId: string) => `/api/v1/shopping-cases/${encodeURIComponent(caseId)}/fulfillment-options`,
  fulfilmentSelection: (caseId: string) => `/api/v1/shopping-cases/${encodeURIComponent(caseId)}/fulfillment-selections`,
  confirmFulfilment: (caseId: string, selectionId: string) => (
    `/api/v1/shopping-cases/${encodeURIComponent(caseId)}/fulfillment-selections/${encodeURIComponent(selectionId)}/confirm-cart`
  ),
};
