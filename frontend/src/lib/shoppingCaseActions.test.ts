import { afterEach, describe, expect, it, vi } from 'vitest';

import { postShoppingCaseAction, shoppingCaseActionPath } from './shoppingCaseActions';


describe('shoppingCaseActions', () => {
  afterEach(() => vi.restoreAllMocks());

  it('centralizes revision-bound action transport and idempotency', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      JSON.stringify({ revision: 3 }), { status: 200, headers: { 'content-type': 'application/json' } },
    ));
    const result = await postShoppingCaseAction(
      shoppingCaseActionPath.fulfilmentSelection('case/a'),
      { expected_revision: 2 }, { idempotencyKey: 'select-123456' },
    );
    expect(result).toMatchObject({ ok: true, status: 200, payload: { revision: 3 } });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/shopping-cases/case%2Fa/fulfillment-selections'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': 'select-123456' }),
      }),
    );
  });
});
