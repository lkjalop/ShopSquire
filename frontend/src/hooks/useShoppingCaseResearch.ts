import { useCallback, useEffect, useRef, useState } from 'react';
import type { AmbiguityExploration } from '../components/AmbiguityExplorationPanel';
import { apiUrl, safeJson } from '../lib/api';
import { csrfHeaders } from '../lib/csrf';

export type ActiveShoppingCase = {
  case_id: string;
  retained_purpose: string;
};

export type ShoppingCaseResearchState = 'idle' | 'running' | 'completed' | 'failed' | 'timed_out';

type ResearchRequest = {
  uid: string;
  refreshAuthorized?: boolean;
  deadlineMs?: number;
};

const requestHeaders = (idempotencyKey?: string) => ({
  'Content-Type': 'application/json',
  ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
  'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
  ...csrfHeaders(),
});

async function postShoppingCase(path: string, body: Record<string, unknown>, idempotencyKey?: string) {
  const response = await fetch(apiUrl(path), {
    method: 'POST', credentials: 'include', headers: requestHeaders(idempotencyKey),
    body: JSON.stringify(body),
  });
  const payload = await safeJson(response);
  if (!response.ok) {
    throw new Error(String(
      payload?.detail?.message || payload?.detail?.code || payload?.detail
      || 'Shopping-case operation failed.',
    ));
  }
  return payload;
}

/**
 * Owns durable shopping-case identity and the cancellable research operation.
 * Rendering and buyer-facing copy deliberately remain outside this hook.
 */
export function useShoppingCaseResearch() {
  const [activeShoppingCase, setActiveShoppingCase] = useState<ActiveShoppingCase | null>(null);
  const [ambiguityExploration, setAmbiguityExploration] = useState<AmbiguityExploration | null>(null);
  const [researchState, setResearchState] = useState<ShoppingCaseResearchState>('idle');
  const controllerRef = useRef<AbortController | null>(null);
  const executionRef = useRef<{ caseId: string; uid: string; executionId: string } | null>(null);

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
    deadlineMs = 20_000,
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
    researchState,
    executeResearch,
    cancelResearch,
    acceptRequirementProposal,
    submitManualSpecifications,
    resolveEvidenceSource,
    approvePublisherCandidate,
  };
}
