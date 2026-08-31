import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { AmbiguityExploration } from '../components/AmbiguityExplorationPanel';
import type { ProductShelfProjection } from '../components/ProductShelvesPanel';
import type { SupplierContinuation } from '../components/SupplierContinuationCard';
import { apiUrl, safeJson } from '../lib/api';
import { csrfHeaders } from '../lib/csrf';

export type ActiveShoppingCase = {
  case_id: string;
  retained_purpose: string;
  uid?: string;
  revision?: number;
  interpretation_job_id?: string;
};

export type ShoppingCaseResearchState = 'idle' | 'running' | 'completed' | 'failed' | 'timed_out';

type ResearchRequest = {
  uid: string;
  refreshAuthorized?: boolean;
  deadlineMs?: number;
  authorizationBasis?: 'buyer_action' | 'tenant_policy';
};

type StateUpdate<T> = T | ((current: T) => T);

export type ShoppingCasePresentationState = {
  activeShoppingCase: ActiveShoppingCase | null;
  ambiguityExploration: AmbiguityExploration | null;
  productShelves: ProductShelfProjection | null;
  supplierContinuation: SupplierContinuation | null;
};

export type ShoppingCasePresentationAction =
  | { type: 'active.replaced'; value: StateUpdate<ActiveShoppingCase | null> }
  | { type: 'ambiguity.replaced'; value: StateUpdate<AmbiguityExploration | null> }
  | { type: 'shelves.replaced'; value: StateUpdate<ProductShelfProjection | null> }
  | { type: 'supplier.replaced'; value: StateUpdate<SupplierContinuation | null> }
  | { type: 'case.cleared' };

export const initialShoppingCasePresentationState: ShoppingCasePresentationState = {
  activeShoppingCase: null,
  ambiguityExploration: null,
  productShelves: null,
  supplierContinuation: null,
};

const applyUpdate = <T,>(current: T, update: StateUpdate<T>): T => (
  typeof update === 'function' ? (update as (value: T) => T)(current) : update
);

export function shoppingCasePresentationReducer(
  state: ShoppingCasePresentationState,
  action: ShoppingCasePresentationAction,
): ShoppingCasePresentationState {
  switch (action.type) {
    case 'active.replaced':
      return { ...state, activeShoppingCase: applyUpdate(state.activeShoppingCase, action.value) };
    case 'ambiguity.replaced':
      return { ...state, ambiguityExploration: applyUpdate(state.ambiguityExploration, action.value) };
    case 'shelves.replaced':
      return { ...state, productShelves: applyUpdate(state.productShelves, action.value) };
    case 'supplier.replaced':
      return { ...state, supplierContinuation: applyUpdate(state.supplierContinuation, action.value) };
    case 'case.cleared':
      return initialShoppingCasePresentationState;
  }
}

const requestHeaders = (idempotencyKey?: string) => ({
  'Content-Type': 'application/json',
  ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
  'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
  ...csrfHeaders(),
});

async function postShoppingCase(
  path: string, body: Record<string, unknown>, idempotencyKey?: string, deadlineMs = 45_000,
) {
  const controller = new AbortController();
  const deadline = globalThis.setTimeout(() => controller.abort('shopping_case_operation_deadline'), deadlineMs);
  try {
    const response = await fetch(apiUrl(path), {
      method: 'POST', credentials: 'include', headers: requestHeaders(idempotencyKey),
      signal: controller.signal, body: JSON.stringify(body),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(String(
        payload?.detail?.message || payload?.detail?.code || payload?.detail
        || 'Shopping-case operation failed.',
      ));
    }
    return payload;
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      throw new Error('Shopping-case operation timed out; no authority was granted. Retry explicitly.');
    }
    throw error;
  } finally {
    globalThis.clearTimeout(deadline);
  }
}

/**
 * Owns durable shopping-case identity and the cancellable research operation.
 * Rendering and buyer-facing copy deliberately remain outside this hook.
 */
export function useShoppingCaseResearch() {
  const [presentation, dispatchPresentation] = useReducer(
    shoppingCasePresentationReducer,
    initialShoppingCasePresentationState,
  );
  const { activeShoppingCase, ambiguityExploration, productShelves, supplierContinuation } = presentation;
  const setActiveShoppingCase = useCallback((value: StateUpdate<ActiveShoppingCase | null>) => {
    dispatchPresentation({ type: 'active.replaced', value });
  }, []);
  const setAmbiguityExploration = useCallback((value: StateUpdate<AmbiguityExploration | null>) => {
    dispatchPresentation({ type: 'ambiguity.replaced', value });
  }, []);
  const setProductShelves = useCallback((value: StateUpdate<ProductShelfProjection | null>) => {
    dispatchPresentation({ type: 'shelves.replaced', value });
  }, []);
  const setSupplierContinuation = useCallback((value: StateUpdate<SupplierContinuation | null>) => {
    dispatchPresentation({ type: 'supplier.replaced', value });
  }, []);
  const [researchState, setResearchState] = useState<ShoppingCaseResearchState>('idle');
  const [researchStartedAt, setResearchStartedAt] = useState<number | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const executionRef = useRef<{ caseId: string; uid: string; executionId: string } | null>(null);

  useEffect(() => {
    const active = activeShoppingCase;
    if (!active?.case_id || !active.interpretation_job_id) return undefined;
    const controller = new AbortController();
    const traceId = active.case_id.replace(/^sc-/, '');
    const expectedRevision = Number(active.revision || 1);

    const applyInterpretations = (
      caseId: string, revision: number, rows: any[], interpretationJob?: Record<string, unknown>,
    ) => {
      if (caseId !== active.case_id || revision !== expectedRevision || rows.length === 0) return;
      setAmbiguityExploration((current) => current?.case_id === active.case_id
        ? {
          ...current, interpretations: rows,
          interpretation_job: interpretationJob || current.interpretation_job,
        }
        : current);
    };

    const applyEvents = (items: any[]) => {
      for (const event of items) {
        if (String(event?.event_type || '') !== 'case_interpretation_completed') continue;
        const payload = event?.payload || {};
        applyInterpretations(
          String(payload.case_id || ''), Number(payload.case_revision || 0),
          Array.isArray(payload.interpretations) ? payload.interpretations : [],
          {
            job_id: payload.job_id, case_revision: payload.case_revision,
            status: 'completed', authority: payload.authority, receipt: payload.receipt,
          },
        );
      }
    };

    void (async () => {
      try {
        // Recover a result completed before this browser connected, then keep
        // listening for the live transition. Both are revision-gated.
        const latest = await fetch(apiUrl(
          `/api/v1/shopping-cases/${encodeURIComponent(active.case_id)}`
            + `/interpretation-jobs/latest?uid=${encodeURIComponent(active.uid || '')}`,
        ), {
          credentials: 'include', signal: controller.signal,
          headers: { 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
        });
        if (latest.ok) {
          const job = await safeJson(latest);
          applyInterpretations(
            String(job?.case_id || ''), Number(job?.case_revision || 0),
            Array.isArray(job?.result?.hypotheses) ? job.result.hypotheses : [],
            job,
          );
        }
        const response = await fetch(apiUrl(
          `/api/v1/trace/${encodeURIComponent(traceId)}/events/stream`,
        ), {
          credentials: 'include', signal: controller.signal,
          headers: { 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
        });
        if (!response.ok || !response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() || '';
          for (const frame of frames) {
            const data = frame.split(/\r?\n/)
              .filter((line) => line.startsWith('data:'))
              .map((line) => line.slice(5).trim())
              .join('\n');
            if (!data) continue;
            try {
              const parsed = JSON.parse(data);
              applyEvents(Array.isArray(parsed) ? parsed : [parsed]);
            } catch { /* malformed observer frames have no buyer authority */ }
          }
        }
      } catch (error: any) {
        if (error?.name !== 'AbortError') {
          // Trace transport is advisory; the deterministic panel remains valid.
        }
      }
    })();
    return () => controller.abort('shopping_case_changed');
  }, [activeShoppingCase]);

  const cancelResearch = useCallback((reason = 'shopping_case_research_cancelled') => {
    const active = executionRef.current;
    if (active) {
      const governedReason = reason === 'research_deadline_exceeded'
        ? 'research_deadline_exceeded'
        : reason === 'shopping_case_research_superseded'
          ? 'research_superseded'
          : reason === 'buyer_departed'
            ? 'buyer_departed'
            : 'buyer_cancelled';
      void fetch(apiUrl(
        `/api/v1/shopping-cases/${encodeURIComponent(active.caseId)}/research-cancel`,
      ), {
        method: 'POST',
        credentials: 'include',
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
          ...csrfHeaders(),
        },
        body: JSON.stringify({
          uid: active.uid,
          execution_id: active.executionId,
          reason: governedReason,
        }),
      }).catch(() => undefined);
    }
    controllerRef.current?.abort(reason);
    controllerRef.current = null;
  }, []);

  useEffect(() => {
    const onPageHide = () => cancelResearch('buyer_departed');
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [cancelResearch]);

  const executeResearch = useCallback(async ({
    uid,
    refreshAuthorized = false,
    // Live official-origin research is bounded to 30 seconds server-side.
    // Give the response time to return and seal its receipts before the buyer
    // transport requests cooperative cancellation.
    deadlineMs = 40_000,
    authorizationBasis = 'buyer_action',
  }: ResearchRequest) => {
    const exploration = ambiguityExploration;
    if (!exploration?.case_id) {
      throw new Error('This exploration is missing its shopping-case identity.');
    }
    if (!exploration.research_plan_id) {
      throw new Error('This case has no governed research plan. Upload requirements or continue provisionally.');
    }

    cancelResearch('shopping_case_research_superseded');
    const controller = new AbortController();
    const executionId = globalThis.crypto?.randomUUID?.()
      || `research-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    controllerRef.current = controller;
    executionRef.current = { caseId: exploration.case_id, uid, executionId };
    setResearchState('running');
    setResearchStartedAt(Date.now());
    const deadline = window.setTimeout(
      () => cancelResearch('research_deadline_exceeded'),
      deadlineMs,
    );
    try {
      const response = await fetch(apiUrl(
        `/api/v1/shopping-cases/${encodeURIComponent(exploration.case_id)}/research`,
      ), {
        method: 'POST',
        credentials: 'include',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
          ...csrfHeaders(),
        },
        body: JSON.stringify({
          uid,
          research_plan_id: exploration.research_plan_id,
          ambiguity_object_ids: (exploration.ambiguity_objects || []).map((item) => item.ambiguity_id),
          hypothesis_ids: (exploration.interpretations || [])
            .map((item) => item.hypothesis_id)
            .filter((value): value is string => Boolean(value)),
          research_authorized: true,
          authorization_basis: authorizationBasis,
          refresh_authorized: refreshAuthorized,
          execution_id: executionId,
        }),
      });
      const payload = await safeJson(response);
      if (!response.ok) {
        throw new Error(String(
          payload?.detail?.message || payload?.detail?.code || payload?.detail
          || 'Approved-source research failed.',
        ));
      }
      setResearchState('completed');
      return payload;
    } catch (error: any) {
      setResearchState(error?.name === 'AbortError' ? 'timed_out' : 'failed');
      throw error;
    } finally {
      window.clearTimeout(deadline);
      if (controllerRef.current === controller) controllerRef.current = null;
      if (executionRef.current?.executionId === executionId) executionRef.current = null;
      setResearchStartedAt(null);
    }
  }, [ambiguityExploration, cancelResearch]);

  const acceptRequirementProposal = useCallback(async ({
    uid, caseId, proposalId, proposalVersion, acceptedClaimIds, rejectedClaimIds,
    corrections = [], researchChoice,
  }: {
    uid: string; caseId: string; proposalId: string; proposalVersion: number;
    acceptedClaimIds: string[]; rejectedClaimIds: string[];
    corrections?: Record<string, unknown>[];
    researchChoice: 'local_only' | 'research_and_corroborate';
  }) => postShoppingCase(
    `/api/v1/shopping-cases/${encodeURIComponent(caseId)}`
      + `/requirement-proposals/${encodeURIComponent(proposalId)}/accept`,
    {
      uid, expected_proposal_version: proposalVersion, accepted_claim_ids: acceptedClaimIds,
      rejected_claim_ids: rejectedClaimIds, corrections, research_choice: researchChoice,
    },
    `accept-${proposalId}-${proposalVersion}`,
  ), []);

  const submitManualSpecifications = useCallback(async (uid: string, text: string) => {
    if (!ambiguityExploration?.case_id) {
      throw new Error('This exploration is missing its shopping-case identity.');
    }
    return postShoppingCase(
      `/api/v1/shopping-cases/${encodeURIComponent(ambiguityExploration.case_id)}`
        + '/requirement-proposals/from-text',
      { uid, text, retained_purpose: ambiguityExploration.retained_purpose },
    );
  }, [ambiguityExploration]);

  const resolveEvidenceSource = useCallback(async (
    uid: string,
    hint: { source_url?: string; vendor_name?: string },
    researchAuthorized: boolean,
  ) => {
    if (!ambiguityExploration?.case_id) {
      throw new Error('This exploration is missing its shopping-case identity.');
    }
    return postShoppingCase(
      `/api/v1/shopping-cases/${encodeURIComponent(ambiguityExploration.case_id)}`
        + '/evidence-source-resolutions',
      { uid, ...hint, research_authorized: researchAuthorized },
    );
  }, [ambiguityExploration]);

  const approvePublisherCandidate = useCallback(async (uid: string, candidate: any) => {
    if (!ambiguityExploration?.case_id) {
      throw new Error('This exploration is missing its shopping-case identity.');
    }
    if (!candidate?.candidate_id || !candidate?.candidate_version) {
      throw new Error('This publisher candidate is not durably bound to the shopping case.');
    }
    return postShoppingCase(
      `/api/v1/shopping-cases/${encodeURIComponent(ambiguityExploration.case_id)}`
        + `/publisher-candidates/${encodeURIComponent(candidate.candidate_id)}/approve`,
      {
        uid, expected_candidate_version: candidate.candidate_version,
        approval_scope: 'case_only',
        allowed_claim_types: [
          'minimum_requirements', 'recommended_requirements', 'target_requirements',
          'compatibility', 'operating_system_support', 'hardware_certification',
        ],
        research_authorized: true,
      },
      `approve-${candidate.candidate_id}-${candidate.candidate_version}`,
    );
  }, [ambiguityExploration]);

  return {
    activeShoppingCase,
    setActiveShoppingCase,
    ambiguityExploration,
    setAmbiguityExploration,
    productShelves,
    setProductShelves,
    supplierContinuation,
    setSupplierContinuation,
    researchState,
    researchStartedAt,
    executeResearch,
    cancelResearch,
    acceptRequirementProposal,
    submitManualSpecifications,
    resolveEvidenceSource,
    approvePublisherCandidate,
  };
}
