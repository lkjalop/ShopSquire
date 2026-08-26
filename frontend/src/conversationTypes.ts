import type { AffordabilityResolution } from './components/AffordabilityResolutionCard';
import type { BuyerClaimReconciliation } from './components/BuyerClaimReconciliationCard';
import type { BuyerRequirementClaim } from './components/BuyerRequirementReviewCard';
import type { PendingCartPlan } from './components/PendingCartChangeCard';

export type NqeInteraction = {
  questionId: string;
  questionText: string;
  optionId: string;
  optionLabel: string;
  optionValue?: string;
  appliedConstraints?: Record<string, any>;
  ts: number;
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  images?: string[];
  disambiguation?: boolean;
  disambiguationOptions?: string[];
  nextQuestions?: { id: string; text: string; goal?: string; why_hint?: string; options?: { id: string; label: string; value?: string }[] }[];
  complexity?: { score: number; tier: string; model: string };
  voiceUsed?: boolean;
  nqeSelection?: NqeInteraction;
  nqeSelectionApplied?: Record<string, any>;
  agentStepsReadable?: string[];
  narrationJobId?: string;
  undoClear?: { items: { sku: string; quantity: number; name?: string }[] };
  undoServer?: boolean;
  cartConfirm?: PendingCartPlan;
  cartPlanStatus?: string;
  affordabilityResolution?: AffordabilityResolution;
  evidence?: any;
  webConsentPrompt?: { query: string };
  buyerRequirementClaims?: BuyerRequirementClaim[];
  buyerRequirementProposal?: { case_id: string; proposal_id: string; proposal_version: number };
  buyerClaimReconciliation?: BuyerClaimReconciliation[];
  responseProvenance?: {
    response_kind?: string;
    interpretation_model?: string | null;
    narration_model?: string | null;
    label: string;
  };
  sourceFetchPrompt?: { sourceUrl: string };
};
