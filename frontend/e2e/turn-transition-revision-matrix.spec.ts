import { expect, test, type APIRequestContext } from '@playwright/test';

const headers = {
  'x-api-key': process.env.VITE_API_KEY || 'local-developer-key',
  'x-tenant-id': 'default',
  'Content-Type': 'application/json',
};

async function completedTurn(
  request: APIRequestContext,
  uid: string,
  query: string,
  shoppingCaseId: string | null,
  idempotencyKey: string,
): Promise<any> {
  const payload = {
    uid,
    query,
    ...(shoppingCaseId ? { shopping_case_id: shoppingCaseId } : {}),
    session_id: uid,
    idempotency_key: idempotencyKey,
  };
  let response = await request.post('/api/v1/chat/query', { headers, data: payload, timeout: 90_000 });
  expect(response.ok(), `chat/query failed (${response.status()})`).toBeTruthy();
  let data = await response.json();
  const deadline = Date.now() + 60_000;
  while (data?.status === 'in_progress' && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, Number(data.retry_after_ms || 500)));
    response = await request.post('/api/v1/chat/query', { headers, data: payload, timeout: 90_000 });
    expect(response.ok()).toBeTruthy();
    data = await response.json();
  }
  expect(data?.status).not.toBe('in_progress');
  return data;
}

test('every conversational transition publishes one matching case revision', async ({ request }) => {
  test.setTimeout(300_000);
  const uid = `turn-matrix-${Date.now()}`;
  let caseId: string | null = null;
  let priorByCase = new Map<string, number>();

  const turns = [
    ['I need a laptop for simulation work.', ['NEW_CATEGORY']],
    ['It must also run Rockwell Emulate3D locally.', ['ADD_WORKLOAD']],
    ['Mostly small PLC models, but occasionally a large factory model.', ['ANSWER_PENDING', 'REFINE_WORKLOAD']],
    ["Actually replace that workload with Baldur's Gate 3.", ['REPLACE_WORKLOAD']],
    ['Actually make it 10 laptops.', ['COMMERCIAL_AMENDMENT']],
  ] as const;

  for (let index = 0; index < turns.length; index += 1) {
    const [query, allowedTransitions] = turns[index];
    // Idempotency keys are operation identities, not turn ordinals. Include the
    // journey identity so retries retrieve this journey's completed envelope
    // without accidentally replaying an earlier test run.
    const data = await completedTurn(request, uid, query, caseId, `${uid}-${index}`);
    const projection = data.turn_read_model;
    expect(projection?.schema_version).toBe('revision-bound-turn-read-model.v1');
    expect(allowedTransitions).toContain(projection.transition);
    expect(Number(data.case_revision)).toBe(Number(projection.case_revision));
    expect(String(data.assistant_message || '')).toBe(String(projection.assistant_message || ''));
    expect(data.right_panel ?? null).toEqual(projection.right_panel ?? null);
    expect(data.products || []).toEqual(projection.products || []);

    const projectionCase = String(projection.case_id);
    const prior = priorByCase.get(projectionCase);
    if (prior != null) expect(Number(projection.case_revision)).toBe(prior + 1);
    priorByCase.set(projectionCase, Number(projection.case_revision));
    caseId = String(data.shopping_case_id || data.ambiguity_exploration?.case_id || projectionCase);
    expect(caseId).toMatch(/^sc-/);
  }
});
