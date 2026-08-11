import { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import styles from './App.module.css';
import ProductGrid from './components/ProductGrid';
import { formatMoney, formatProductPrice, normalizeCurrency } from './lib/money';
import StorefrontEmphasisBanner from './components/StorefrontEmphasisBanner';
import FulfilmentOptions, { type FulfilmentCaseSummary } from './components/FulfilmentOptions';
import SourcingIntentCard from './components/SourcingIntentCard';
import MultiIntentCard from './components/MultiIntentCard';
import PendingCartChangeCard, { type PendingCartPlan } from './components/PendingCartChangeCard';
import BulkAlternatives, { type BulkAlternativeOption } from './components/BulkAlternatives';
import ExternalResearchPanel, { type ExternalResearchItem } from './components/ExternalResearchPanel';
import DecisionTrace from './components/DecisionTrace';
import EscalationRoom from './components/EscalationRoom';
import RightPanelExtras from './components/RightPanelExtras';
import RecommendationShelf, { type RecommendationShelfContract } from './components/RecommendationShelf';
import AffordabilityResolutionCard, {
  type AffordabilityResolution,
} from './components/AffordabilityResolutionCard';
import { apiUrl, getApiBase, safeJson, getCart, addCartItem, removeCartItem, setCartItemQty, clearCart, undoCartClear, applyCartMutation, rejectCartMutation, emitConsumerSignal, emitPageView, type SourcingIntent, type MultiIntentPlan } from './lib/api';
import { nextSourcingTraceId, procurementAwareTraceId } from './lib/trace';
import { normalizePendingBulkBudget } from './lib/bulkBudget';
import { previousSessionSkus, keepAfterClear } from './lib/cartSession';
import { citationChips } from './lib/evidenceDisplay';
import { sourcingIntentAfterSelection } from './lib/sourcing';
import { nonRecommendationOutcome } from './lib/chatOutcome';
import { apiErrorMessage } from './lib/apiError';
import { selectProportionateAlternatives } from './lib/proportionateAlternatives';
import { isActionableBuyerQuestion } from './lib/buyerQuestion';
import { isUnsupportedPostPurchaseTracking } from './lib/postPurchaseIntent';
import { isUnusableImageEvidence } from './lib/imageEvidenceAuthority';
import AttachmentButton from './components/AttachmentButton';
import DisambiguationButtons from './components/DisambiguationButtons';
import { useDualSTT } from './hooks/useDualSTT';
import CartPanel from './components/CartPanel';
import LoginModal from './components/LoginModal';
import AdminDashboard from './components/AdminDashboard';
import { productShortLabel } from './lib/productDisplay';
import { csrfHeaders } from './lib/csrf';
import { detectPII } from './lib/pii';
import StorefrontTrustBanner, {
  trustEvidenceFromPayload,
  type CatalogueLoadState,
  type TrustEvidence,
} from './components/StorefrontTrustBanner';
import ProductWhyEvidence, { type ProductWhyExplanation } from './components/ProductWhyEvidence';
import InlineMessageText from './components/InlineMessageText';
import BuyerRequirementReviewCard, {
  type BuyerRequirementClaim,
} from './components/BuyerRequirementReviewCard';
import BuyerClaimReconciliationCard, {
  type BuyerClaimReconciliation,
} from './components/BuyerClaimReconciliationCard';
import ProductShelvesPanel, { type ProductShelfProjection, type ShelfProduct } from './components/ProductShelvesPanel';
import SupplierContinuationCard, {
  type SupplierContinuation,
} from './components/SupplierContinuationCard';
import AmbiguityExplorationPanel, { type AmbiguityExploration } from './components/AmbiguityExplorationPanel';
import {
  detectCVIssueType,
  detectPanelMode,
  hasDamageSignal,
  isCartUpsellIntentQuery,
  isComplaintIntent,
  isShoppingIntentQuery,
  requiresExternalResearchConsent,
  shouldRouteToComplaint,
  type RightPanelMode,
} from './lib/queryIntent';
import {
  clearStoredAuthIdentity,
  clearStoredRole,
  clearStoredUid,
  getStoredAuthIdentity,
  getOrCreateStoredUid,
  getOrCreateConversationEpoch,
  rotateConversationEpoch,
  setStoredAuthIdentity,
} from './lib/browserSession';

export type Product = {
  sku: string;
  name: string;
  display_name?: string;
  subtitle?: string;
  price: number;
  currency?: string;
  features?: string[];
  image_url?: string;
  specs?: Record<string, any>;
  why?: string[];
  score_norm?: number;
  why_codes?: { code: string; label: string; confidence: number; weight?: number; weighted_score?: number }[];
  why_confidence?: number;
  model_source?: string;
  // Stock honesty — surfaced from the backend finalizer (stock_status/stock_level/stock_urgency/cart_eligible).
  stock_status?: 'in_stock' | 'low_stock' | 'very_low_stock' | 'out_of_stock' | string;
  stock_level?: number;
  stock_urgency?: string;
  cart_eligible?: boolean;
};
type NqeInteraction = {
  questionId: string;
  questionText: string;
  optionId: string;
  optionLabel: string;
  optionValue?: string;
  appliedConstraints?: Record<string, any>;
  ts: number;
};
type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  images?: string[];           // data-URL thumbnails shown inline
  disambiguation?: boolean;    // true → render DisambiguationButtons
  disambiguationOptions?: string[];
  nextQuestions?: { id: string; text: string; goal?: string; why_hint?: string; options?: { id: string; label: string; value?: string }[] }[];
  complexity?: { score: number; tier: string; model: string };
  voiceUsed?: boolean;
  nqeSelection?: NqeInteraction;         // set on user msgs triggered by NQE option click
  nqeSelectionApplied?: Record<string, any>;  // echoed back from backend on assistant msgs
  agentStepsReadable?: string[];         // human-readable agent step summaries from ResponseNormalizer
  narrationJobId?: string;               // async-narration handoff: poll /narration/{id} → replace content
  undoClear?: { items: { sku: string; quantity: number; name?: string }[] };  // "Undo" chip after a clear → re-add these
  undoServer?: boolean;                  // V2 cart lane: undo via the server-side snapshot (POST /cart/undo)
  // V2 cart lane (C2): a CONFIRM-tier mutation plan — nothing has touched the cart yet; the
  // Confirm button applies it via POST /cart/mutations/{plan_id}/apply (idempotent, stale-guarded).
  cartConfirm?: PendingCartPlan;
  cartPlanStatus?: string;
  affordabilityResolution?: AffordabilityResolution;
  evidence?: any;                        // N1: evidence block from the orchestrator → source chips + Evidence tab
  webConsentPrompt?: { query: string };  // N3 Mode-B: consent chip — never auto-search on an imperative
  buyerRequirementClaims?: BuyerRequirementClaim[];
  buyerRequirementProposal?: {
    case_id: string;
    proposal_id: string;
    proposal_version: number;
  };
  buyerClaimReconciliation?: BuyerClaimReconciliation[];
};
type PendingImageContext = {
  labels: string[];
  ocrText: string;
  imageHash?: string | null;
};
type PanelTier = {
  title?: string;
  items?: Product[];
  explanation?: string;
};
type AnchorSection = {
  anchor_id?: string;
  title?: string;
  source_image_hash?: string;
  anchor_hint?: { brand?: string; use_case?: string; ocr_excerpt?: string };
  top_products?: Product[];
  summary?: string;
  match_basis?: string[];
};
type RightPanelContract = {
  mode?: 'shopping' | 'support';
  show_tiers?: boolean;
  budget_status?: string;
  summary?: string;
  image_untrusted?: boolean;
  image_degraded_mode?: boolean;
  security_route?: string;
  security_summary?: string;
  lower_tier?: PanelTier;
  higher_tier?: PanelTier;
  anchor_sections?: AnchorSection[];
  // Phase-3 storefront-emphasis lever: a gated, profile-sourced messaging line for treatment users.
  // Present only when the experiment is live + the subject is treatment + the action gate allowed.
  emphasis?: { text?: string; variant?: string; key?: string; applied?: boolean; experiment_id?: string };
  // Backend-driven choice lanes (recommend_choice_lanes): evidence-grouped options. When present the UI
  // renders THESE instead of the frontend heuristic. A work query marks office lanes primary and a gaming
  // chassis non_primary, so gaming never appears as a primary work pick.
  device_lanes?: BackendDeviceLane[];
  // Procurement-truth advisory: when a work query has no primary-fit options (only specialty/gaming),
  // the backend advises sourcing rather than presenting gaming as the answer.
  fleet_advisory?: { coverage?: string; message?: string; suggest_procurement?: boolean; non_primary_lanes?: string[] };
};
type BackendDeviceLane = {
  key: string;
  title: string;
  explanation?: string;
  metrics?: string[];
  primary?: boolean;
  non_primary?: boolean;
  count?: number;
  price_min?: number | null;
  price_max?: number | null;
  skus?: string[];
  products?: { sku: string; name: string; price?: number | null; why?: string[] }[];
};

const IMAGE_FAST_TRIAGE_TIMEOUT_MS = 3000;
const IMAGE_DEEP_TRIAGE_DELAY_MS = 30000;

// Async-narration poll registry: a job id is live while its poll chain is allowed to run.
// tick() bails when its id is gone, so deleting from this Set is the cancellation mechanism
// — without it every message spawned an un-cancellable setTimeout→fetch chain (zombie fetches
// kept hitting /narration/{id} long after the message was replaced).
const activeNarrationJobs = new Set<string>();

type BackendStatus = {
  ok: boolean;
  latencyMs: number | null;
  checkedAt: Date | null;
  error?: string | null;
};

type ReadyComponent = {
  status?: string;
  details?: Record<string, any>;
};

type ReadyzResponse = {
  status?: string;
  components?: Record<string, ReadyComponent>;
  reasons?: string[];
};

type OperatorMetricSnapshot = {
  catalogProfileCacheHit?: boolean | null;
  catalogProfileMs?: number | null;
  routeTotalMs?: number | null;
  ollamaSummaryMs?: number | null;
  qrDecodeSuccess?: boolean | null;
  linkedArtifactFetch?: boolean | null;
  securityReviewRequired?: boolean | null;
  recommendationTimeout?: boolean | null;
  recommendationFallbackUsed?: boolean | null;
  traceId?: string | null;
  source?: string | null;
  recordedAt?: string | null;
};

type DeviceLane = 'windows' | 'macbook' | 'tablet_chromebook';

function normalizeTraceId(value: any): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || null;
  }
  if (value && typeof value === 'object') {
    for (const key of ['trace_id', 'decision_trace_id', 'decision_id', 'case_id', 'id']) {
      const nested = (value as any)?.[key];
      if (typeof nested === 'string' && nested.trim()) return nested.trim();
    }
  }
  return null;
}

function productPrice(p: any): number {
  const direct = Number(p?.price);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const cents = Number(p?.price_cents);
  if (Number.isFinite(cents) && cents > 0) return cents / 100;
  return 0;
}

// Render a product price honestly: a real amount when we have one (from price OR price_cents), and an
// em-dash when the object carries no price — never a misleading "$0" (demo-truth, same class as the
// $0 budget-band fix).
function formatPrice(p: any): string {
  return formatProductPrice(p);
}


function laneForProduct(p: Product): DeviceLane {
  const name = String(p.name || '').toLowerCase();
  const features = (p.features || []).join(' ').toLowerCase();
  const text = `${name} ${features}`;
  if (/macbook|apple m[0-9]|mac os|macos/.test(text)) return 'macbook';
  if (/chromebook|chrome os|tablet|ipad|2-in-1|2 in 1|detachable/.test(text)) return 'tablet_chromebook';
  return 'windows';
}

function laneTitle(lane: DeviceLane): string {
  if (lane === 'macbook') return 'MacBook Options';
  if (lane === 'tablet_chromebook') return 'Tablet / Chromebook Options';
  return 'Windows Laptop Options';
}

function _prettyReason(reason: string): string {
  const r = String(reason || '').trim();
  if (!r) return '';
  if (/^\+?embedding_similarity$/i.test(r)) return 'close visual/spec match';
  if (/^\+?cross_encoder$/i.test(r)) return 'strong semantic match';
  if (/^\+?in_stock$/i.test(r)) return 'in stock';
  if (/^\+?price_fit$/i.test(r)) return 'fits the budget';
  if (/^\+?use_case_match/i.test(r)) return 'fits this use case';
  return r.replace(/^[+-]/, '').replace(/_/g, ' ');
}

function _shortUseCase(query: string): string {
  const q = String(query || '').toLowerCase();
  if (/highschool|high school|yr\s?(?:7|8|9|10|11|12)|year\s?(?:7|8|9|10|11|12)|teen/.test(q)) return 'high school';
  if (/student|university|uni|college/.test(q)) return 'study';
  if (/gaming|fps|rtx|gpu/.test(q)) return 'gaming';
  if (/office|work|excel|meetings|zoom/.test(q)) return 'work';
  if (/design|video|editing|creator|creative/.test(q)) return 'creative';
  return 'daily use';
}

function _stripTechnicalTokens(text: string): string {
  return String(text || '')
    .replace(/\(\s*[+-]?[a-z_]+(?:\s*,\s*[+-]?[a-z_]+)*\s*\)/gi, '')
    .replace(/\b[+-](?:embedding_similarity|cross_encoder|in_stock|price_fit|use_case_match)\b/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function laneSummary(lane: DeviceLane, items: Product[], budgetStatus?: string, query?: string): string {
  if (!items.length) {
    if (lane === 'tablet_chromebook') return 'No strong tablet/chromebook inventory match yet. Consider widening budget or screen-size range.';
    return 'No close matches in this lane right now. Try adjusting budget or use-case filters.';
  }
  const prices = items.map((p) => productPrice(p)).filter((v) => v > 0);
  const minPrice = prices.length ? Math.min(...prices) : 0;
  const maxPrice = prices.length ? Math.max(...prices) : 0;
  const currencies = Array.from(new Set(items.map((p) => normalizeCurrency((p as any)?.currency))));
  const priceRange = currencies.length === 1
    ? `${formatMoney(minPrice, currencies[0])} to ${formatMoney(maxPrice, currencies[0])}`
    : 'multiple currencies (conversion required before comparison)';
  const useCase = _shortUseCase(String(query || ''));
  const top = items.slice(0, 2).map((p) => {
    const reason = Array.isArray(p.why) && p.why.length > 0 ? _prettyReason(String(p.why[0])) : '';
    const label = productShortLabel(p);
    return reason ? `${label} (${reason})` : label;
  });
  const budgetHint = String(budgetStatus || '').toLowerCase().includes('low')
    ? 'Budget is tight, so value-focused picks are prioritized.'
    : String(budgetStatus || '').toLowerCase().includes('high')
      ? 'Budget allows performance-oriented options.'
      : 'Recommendations balance value and use-case fit.';
  if (lane === 'windows') {
    return `${budgetHint} Top ${useCase} options are ${top.join(' and ')}. Windows picks span ${priceRange}.`;
  }
  if (lane === 'macbook') {
    return `${budgetHint} ${top.join(' and ')} are prioritized for battery life and reliability, spanning ${priceRange}.`;
  }
  return `${budgetHint} Tablet/Chromebook alternatives are shown when portability or price make more sense (${top.join(' and ')}, ${priceRange}).`;
}


function useProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [catalogueState, setCatalogueState] = useState<CatalogueLoadState>('loading');
  const [catalogueEvidence, setCatalogueEvidence] = useState<TrustEvidence>(() => trustEvidenceFromPayload(null));
  useEffect(() => {
    const ctl = new AbortController();
    fetch('/ui/products.json', { signal: ctl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`catalogue_failed (${r.status})`);
        return r.json();
      })
      .then((d) => {
        const nextProducts = Array.isArray(d) ? d : Array.isArray(d?.products) ? d.products : [];
        setProducts(nextProducts);
        setCatalogueEvidence(trustEvidenceFromPayload(Array.isArray(d) ? null : d));
        setCatalogueState(nextProducts.length > 0 ? 'ready' : 'empty');
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return;
        setProducts([]);
        setCatalogueState('unavailable');
      });
    return () => ctl.abort();
  }, []);
  return { products, catalogueState, catalogueEvidence };
}

// PII Detection - Luhn algorithm for credit card validation
// SVG Icons
const ChatIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={styles.fabIcon}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>;
const CloseIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M18 6L6 18M6 6l12 12"/></svg>;
const GearIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>;
const DetachIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="18" height="18"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>;
const MicIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>;
const SendIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>;
const GridIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>;
const ListIcon = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>;

export default function App() {
  const { products, catalogueState, catalogueEvidence } = useProducts();
  const [trustEvidence, setTrustEvidence] = useState<TrustEvidence>(() => trustEvidenceFromPayload(null));
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [headerSearchValue, setHeaderSearchValue] = useState('');
  const localEnvironment = Boolean(
    (import.meta as any).env?.DEV
    || (typeof window !== 'undefined' && ['localhost', '127.0.0.1'].includes(window.location.hostname)),
  );
  useEffect(() => {
    setTrustEvidence((current) => ({
      synthetic: catalogueEvidence.synthetic ?? current.synthetic,
      shadow: catalogueEvidence.shadow ?? current.shadow,
      humanApprovalRequired: catalogueEvidence.humanApprovalRequired ?? current.humanApprovalRequired,
      provenance: catalogueEvidence.provenance ?? current.provenance,
    }));
  }, [catalogueEvidence]);
  const mergeTrustEvidence = (payload: any) => {
    const observed = trustEvidenceFromPayload(payload);
    setTrustEvidence((current) => ({
      synthetic: observed.synthetic ?? current.synthetic,
      shadow: observed.shadow ?? current.shadow,
      humanApprovalRequired: observed.humanApprovalRequired ?? current.humanApprovalRequired,
      provenance: observed.provenance ?? current.provenance,
    }));
  };

  const handleHeaderSearch = () => {
    const q = headerSearchValue.trim();
    if (!q) return;
    setInputValue(q);
    setHeaderSearchValue('');
    setChatOpen(true);
    setTimeout(() => handleSend({ queryOverride: q }), 120);
  };
  const [inputValue, setInputValue] = useState('');
  const [rightPanelMode, setRightPanelMode] = useState<RightPanelMode>('none');
  const [rightPanelPrevMode, setRightPanelPrevMode] = useState<RightPanelMode | null>(null);
  const [rightPanelContract, setRightPanelContract] = useState<RightPanelContract | null>(null);
  const [recommendationShelf, setRecommendationShelf] = useState<RecommendationShelfContract | null>(null);
  const [productShelves, setProductShelves] = useState<ProductShelfProjection | null>(null);
  const [supplierContinuation, setSupplierContinuation] = useState<SupplierContinuation | null>(null);
  const [ambiguityExploration, setAmbiguityExploration] = useState<AmbiguityExploration | null>(null);
  const [activeShoppingCase, setActiveShoppingCase] = useState<{
    case_id: string;
    retained_purpose: string;
  } | null>(null);
  const [displayProducts, setDisplayProducts] = useState<Product[]>([]);
  // Safe-internet-search results (separate labeled source; never owned catalog items).
  const [externalResearch, setExternalResearch] = useState<ExternalResearchItem[]>([]);
  const [fulfilmentCase, setFulfilmentCase] = useState<FulfilmentCaseSummary | null>(null);
  const [sourcingIntent, setSourcingIntent] = useState<SourcingIntent | null>(null);
  // Operational amendments can arrive after a buyer selected a cart item even
  // when the original recommendation did not emit a sourcing preview. Keep
  // these bounded backend facts independently so CartPanel sends them at the
  // commitment boundary instead of relying on a product-slate object.
  const [procurementRequirements, setProcurementRequirements] = useState<Record<string, any>>({});
  // The decision trace of the TURN that produced the sourcing preview — pinned so a later turn's trace
  // doesn't advance past it. confirm-cart links the case to THIS trace, so the Decision-Trace procurement
  // badge resolves against the decision that actually opened the journey (not whatever turn is latest).
  const [sourcingTraceId, setSourcingTraceId] = useState<string | null>(null);
  // Keep the first confirmed procurement request identity above CartPanel.
  // Conversational turns temporarily unmount that panel; amendments must still
  // supersede the original order group instead of creating a parallel RFQ.
  const [confirmedSourcingOrderId, setConfirmedSourcingOrderId] = useState<string | null>(null);
  // P0 multi-intent plan (amend chosen qty + scoped new lines) surfaced for buyer confirmation.
  const [multiIntent, setMultiIntent] = useState<MultiIntentPlan | null>(null);
  const [bulkAlternatives, setBulkAlternatives] = useState<BulkAlternativeOption[]>([]);
  const [tierFilter, setTierFilter] = useState<'all' | 'lower' | 'higher'>('all');
  const [traceId, setTraceId] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceInitialTab, setTraceInitialTab] = useState<string | undefined>(undefined);
  const [traceEvidence, setTraceEvidence] = useState<any | null>(null);  // N1: evidence block for the trace popup's Evidence tab
  // Bulk-order carry-through: the conversation's parsed unit count ("15 work laptops" → 15). Add buttons
  // land THIS qty (sourcing-aware) instead of a silent 1. Cleared/updated on every chat turn.
  const [pendingBulkQty, setPendingBulkQty] = useState<number | null>(null);
  const [pendingBulkBudget, setPendingBulkBudget] = useState<Record<string, any> | null>(null);
  // Session hygiene: a PRIOR session's cart must never silently shape this conversation (stale items were
  // inflating totals in the demo). On first chat open with a non-empty cart, disclose it + how to clear.
  const staleCartNoticeShown = useRef(false);
  // Deep-link: /?trace=<id>&tracetab=procurement opens the Decision Trace straight onto a tab. Lets an
  // operator/demo jump to a specific decision (e.g. the procurement drafted-RFQ + audit) without replaying
  // the whole turn — also what makes the Procurement-tab recording deterministic.
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      const t = (p.get('trace') || '').trim();
      if (t) {
        setTraceId(t);
        setTraceInitialTab((p.get('tracetab') || '').trim() || undefined);
        setTraceOpen(true);
      }
    } catch { /* no query params available — ignore */ }
  }, []);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>({ ok: false, latencyMs: null, checkedAt: null, error: null });
  const [readinessOpen, setReadinessOpen] = useState(false);
  const [readyz, setReadyz] = useState<ReadyzResponse | null>(null);
  const [readyzLoading, setReadyzLoading] = useState(false);
  const [operatorMetrics, setOperatorMetrics] = useState<OperatorMetricSnapshot | null>(() => {
    try {
      const raw = localStorage.getItem('shopsquire_operator_metrics');
      return raw ? JSON.parse(raw) as OperatorMetricSnapshot : null;
    } catch {
      return null;
    }
  });
  const [escalationOpen, setEscalationOpen] = useState(false);
  const [escalationIncidentId, setEscalationIncidentId] = useState<string | null>(null);
  const [escalationBuyerToken, setEscalationBuyerToken] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [isThinking, setIsThinking] = useState(false);
  const [streamAcknowledgement, setStreamAcknowledgement] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatBodyRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [cvPrefillImages, setCvPrefillImages] = useState<File[]>([]);
  const [cvAutoIssueType, setCvAutoIssueType] = useState<string | undefined>(undefined);
  const [imageTriageContexts, setImageTriageContexts] = useState<any[]>([]);
  const [imageTriageRaw, setImageTriageRaw] = useState<any[]>([]);
  const [canonicalImageProducts, setCanonicalImageProducts] = useState<Product[] | null>(null);
  const [canonicalImageSummary, setCanonicalImageSummary] = useState('');
  const [visualSearchQuery, setVisualSearchQuery] = useState('');
  const [pendingImageContext, setPendingImageContext] = useState<PendingImageContext | null>(null);
  const [imageRoutingInFlight, setImageRoutingInFlight] = useState(false);
  const [lastCvSecurityNoteKey, setLastCvSecurityNoteKey] = useState<string | null>(null);
  const [whyDrawerSku, setWhyDrawerSku] = useState<string | null>(null);
  const [whyDrawerData, setWhyDrawerData] = useState<ProductWhyExplanation | null>(null);
  const [whyDrawerLoading, setWhyDrawerLoading] = useState(false);
  const [whyDrawerError, setWhyDrawerError] = useState<string | null>(null);
  const uid = getOrCreateStoredUid();
  const [conversationEpoch, setConversationEpoch] = useState(() => getOrCreateConversationEpoch());
  const [temporaryChat, setTemporaryChat] = useState(false);
  // Dev-only debug metadata (LLM tier·model badge) is noise for a pilot buyer OR a live demo (the demo runs
  // the Vite dev server, so a DEV auto-enable leaks the badge on camera). Show it ONLY on an explicit opt-in
  // (localStorage 'shopsquire_debug'='1') — never to a normal shopper and never by default in a dev build.
  const showDebugBadges = ((): boolean => {
    // `localStorage` (even `typeof localStorage`) can THROW SecurityError in a sandboxed iframe / locked-down
    // privacy context — a bare check here would blank the whole app, so guard the access.
    try {
      return typeof localStorage !== 'undefined' && localStorage.getItem('shopsquire_debug') === '1';
    } catch { return false; }
  })();

  // Track 2b — real clickstream: emit a first-touch page_view (with any ?utm_* channel) so the marketing-BI
  // channel / verified-human / network panels populate from an ACTUAL visit, not just the synthetic seed.
  // Best-effort + privacy-first (server hashes ids, drops raw IP); emitPageView de-dupes to once per load.
  useEffect(() => { emitPageView(uid); }, [uid]);

  const persistOperatorMetrics = useCallback((timing: any, nextTraceId?: string | null, source = 'chat') => {
    if (!timing || typeof timing !== 'object') return;
    const prev = operatorMetrics && typeof operatorMetrics === 'object' ? operatorMetrics : {};
    const snapshot: OperatorMetricSnapshot = {
      ...prev,
      catalogProfileCacheHit:
        typeof timing.catalog_profile_cache_hit === 'boolean'
          ? timing.catalog_profile_cache_hit
          : timing.catalog_profile_cache_hit == null
            ? null
            : Boolean(timing.catalog_profile_cache_hit),
      catalogProfileMs: timing.catalog_profile_ms == null ? null : Number(timing.catalog_profile_ms) || 0,
      routeTotalMs: timing.route_total_ms == null ? null : Number(timing.route_total_ms) || 0,
      ollamaSummaryMs: timing.ollama_summary_ms == null ? null : Number(timing.ollama_summary_ms) || 0,
      qrDecodeSuccess:
        typeof timing.qr_decode_success === 'boolean'
          ? timing.qr_decode_success
          : prev.qrDecodeSuccess ?? null,
      linkedArtifactFetch:
        typeof timing.linked_artifact_fetch === 'boolean'
          ? timing.linked_artifact_fetch
          : prev.linkedArtifactFetch ?? null,
      securityReviewRequired:
        typeof timing.security_review_required === 'boolean'
          ? timing.security_review_required
          : prev.securityReviewRequired ?? null,
      recommendationTimeout:
        typeof timing.recommendation_timeout === 'boolean'
          ? timing.recommendation_timeout
          : prev.recommendationTimeout ?? null,
      recommendationFallbackUsed:
        typeof timing.recommendation_fallback_used === 'boolean'
          ? timing.recommendation_fallback_used
          : prev.recommendationFallbackUsed ?? null,
      traceId: nextTraceId || null,
      source,
      recordedAt: new Date().toISOString(),
    };
    setOperatorMetrics(snapshot);
    try {
      localStorage.setItem('shopsquire_operator_metrics', JSON.stringify(snapshot));
    } catch {}
  }, []);

  const switchRightPanelMode = useCallback((nextMode: RightPanelMode) => {
    setRightPanelMode((prevMode) => {
      if (prevMode !== nextMode) {
        setRightPanelPrevMode(prevMode);
      }
      return nextMode;
    });
  }, []);

  const toImageTriageContexts = useCallback((triageResults: any[], files: File[]) => {
    return triageResults.map((t: any, idx: number) => ({
      ...(t || {}),
      labels: Array.isArray(t?.labels) ? t.labels : [],
      ocr_text:
        (typeof t?.security?.extracted_text === 'string' ? t.security.extracted_text : '')
        || (typeof t?.extracted_text === 'string' ? t.extracted_text : ''),
      cv_signals: {
        ...(typeof t?.security?.signals === 'object' && t.security.signals ? t.security.signals : {}),
        qr_code_detected: Boolean(t?.security?.signals?.qr_code_detected),
        qr_prompt_injection: Boolean(t?.security?.signals?.qr_prompt_injection),
        manipulation_detected: Boolean(t?.security?.signals?.manipulation_detected),
        qr_external_url_detected: Boolean(
          t?.security?.signals?.qr_external_url_detected || t?.security?.signals?.qr_external_url
        ),
        qr_redirect_probe:
          (typeof t?.security?.qr_redirect_probe === 'object' && t.security.qr_redirect_probe)
          ? t.security.qr_redirect_probe
          : {},
        qr_policy_action: t?.qr_assessment?.policy_action || t?.security?.signals?.qr_policy_action || null,
        qr_benign_detected: Boolean(t?.security?.signals?.qr_benign_detected),
        analysis_pending: Boolean(t?.analysis_state?.analysis_pending || t?.artifact?.state === 'pending'),
        analysis_degraded: Boolean(t?.analysis_state?.analysis_degraded || t?.artifact?.state === 'degraded'),
        upload_rejected: Boolean(t?._upload_error),
        upload_error: t?._upload_error || null,
        artifact_state: t?.artifact?.state || t?.security?.artifact_state || null,
      },
      source_name: files[idx]?.name || `Image ${idx + 1}`,
      // Propagate damage/repair intent signals so ImageRecommendPanel can gate on them
      intent_routing: (typeof t?.intent_routing === 'object' && t.intent_routing) ? t.intent_routing : null,
      damage_score: typeof t?.damage_score === 'number' ? t.damage_score : null,
    }));
  }, []);

  const makeClientFastImageTriage = useCallback((file: File, artifactId: string) => {
    const filenameHint = file.name.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ').trim();
    const suspiciousName = /\b(ssn|qr|password|credential|token|secret|invoice|receipt)\b/i.test(filenameHint);
    return {
      _filename: file.name,
      filename: file.name,
      provider: 'client_fast_boundary',
      labels: filenameHint ? [filenameHint] : [],
      extracted_text: '',
      damage_score: 0,
      intent: 'visual_search',
      intent_routing: {
        intent: 'visual_search',
        confidence: 0.2,
        reason: 'client_safe_hint_before_deep_triage',
      },
      security: {
        clean: false,
        artifact_state: 'pending',
        commercial_authority: 'blocked',
        signals: {
          fast_triage_timeout: true,
          filename_suspicious: suspiciousName,
          analysis_pending: true,
        },
        analysis_stage: 'client_safe_hint',
        verdict: 'Image bytes are queued for background security inspection. The attachment cannot influence recommendations or commercial actions yet.',
      },
      artifact: { artifact_id: artifactId, state: 'pending', authority: 'blocked' },
      analysis_state: { analysis_pending: true, analysis_degraded: false, security_risk: suspiciousName },
    };
  }, []);

  const fetchImageTriages = useCallback(async (
    files: File[], fast = false, extractTextEvidence = false,
  ) => {
    const triagePromises = files.map(async (file) => {
      const artifactId = String((file as any).__shopsquireArtifactId || crypto.randomUUID());
      (file as any).__shopsquireArtifactId = artifactId;
      const fd = new FormData();
      fd.append('image', file);
      const triageParams = new URLSearchParams({ artifact_id: artifactId });
      if (fast) triageParams.set('fast', '1');
      if (extractTextEvidence) triageParams.set('extract_text', '1');
      const triagePath = `/api/v1/vision/triage?${triageParams.toString()}`;
      const controller = new AbortController();
      const timeoutId = fast
        ? window.setTimeout(() => controller.abort(), IMAGE_FAST_TRIAGE_TIMEOUT_MS)
        : null;
      try {
        const r = await fetch(apiUrl(triagePath), {
          method: 'POST',
          credentials: 'include',
          body: fd,
          signal: controller.signal,
          headers: {
            'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
            'x-skip-observer': '1',
          },
        });
        const data = await safeJson(r);
        if (!r.ok) {
          const detail = data?.detail || {};
          const error = typeof detail === 'string'
            ? detail
            : String(detail?.error || `upload_rejected_${r.status}`);
          const message = typeof detail === 'object' && detail?.message
            ? String(detail.message)
            : 'This attachment was rejected and was not used.';
          return {
            _filename: file.name,
            filename: file.name,
            _upload_error: error,
            _http_status: r.status,
            labels: [],
            extracted_text: '',
            artifact: detail?.artifact || { artifact_id: artifactId, state: 'quarantined', authority: 'blocked' },
            analysis_state: { analysis_pending: false, analysis_degraded: false, security_risk: true },
            security: {
              clean: false,
              artifact_state: 'quarantined',
              commercial_authority: 'blocked',
              verdict: message,
              reupload_needed: true,
              signals: { upload_rejected: true, upload_error: error },
            },
          };
        }
        if (!data) {
          return {
            _filename: file.name,
            filename: file.name,
            _upload_error: 'invalid_triage_response',
            labels: [],
            artifact: { state: 'degraded', authority: 'blocked' },
            analysis_state: { analysis_degraded: true, security_risk: false },
            security: {
              clean: false,
              artifact_state: 'degraded',
              commercial_authority: 'blocked',
              verdict: 'Inspection did not return a valid result. The attachment was not used.',
              signals: { analysis_degraded: true, invalid_triage_response: true },
            },
          };
        }
        data._filename = file.name;
        return data;
      } catch {
        if (fast) return makeClientFastImageTriage(file, artifactId);
        return {
          _filename: file.name,
          filename: file.name,
          _upload_error: 'triage_unavailable',
          labels: [],
          artifact: { state: 'degraded', authority: 'blocked' },
          analysis_state: { analysis_degraded: true, security_risk: false },
          security: {
            clean: false,
            artifact_state: 'degraded',
            commercial_authority: 'blocked',
            verdict: 'Image inspection is unavailable. The attachment was not used.',
            signals: { analysis_degraded: true, triage_unavailable: true },
          },
        };
      } finally {
        if (timeoutId != null) window.clearTimeout(timeoutId);
      }
    });
    return (await Promise.all(triagePromises)).filter(Boolean);
  }, [makeClientFastImageTriage]);

  const fetchSupportAnswer = useCallback(async (question: string): Promise<string | null> => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 3000);
    try {
      const params = new URLSearchParams({ question });
      const r = await fetch(apiUrl(`/api/v1/support/answer?${params.toString()}`), {
        method: 'POST',
        credentials: 'include',
        signal: controller.signal,
        headers: {
          ...csrfHeaders(),
          'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
          'x-skip-observer': '1',
        },
      });
      if (!r.ok) return null;
      const data = await safeJson(r);
      const answer = String(data?.answer || '').trim();
      return answer || null;
    } catch {
      return null;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }, []);

  const handleRightPanelBack = useCallback(() => {
    if (!rightPanelPrevMode || rightPanelPrevMode === rightPanelMode) return;
    const current = rightPanelMode;
    setRightPanelMode(rightPanelPrevMode);
    setRightPanelPrevMode(current);
  }, [rightPanelMode, rightPanelPrevMode]);
  const [cart, setCart] = useState<any | null>(null);
  // Session hygiene: a PRIOR session's cart must never silently shape this conversation (stale items were
  // inflating totals in the demo). On first chat open, disclose a CARRIED cart + how to clear — but only
  // when the backend age says it's genuinely carried (idle > 1h). The old code called ANY non-empty cart
  // "from a previous session", so a cart built moments ago got mislabeled and, on "clear previous", wiped.
  // Now the label is the truth (backend `cart.age` = now − updated_at), and a fresh working cart is left
  // alone. Unknown age (no timestamp) → stay silent rather than guess.
  useEffect(() => {
    if (!chatOpen || staleCartNoticeShown.current) return;
    const items: any[] = cart?.items || [];
    if (items.length === 0) return;
    const age = cart?.age || null;
    if (!age || !age.is_carried) return;   // fresh this-session cart → not "previous", do not nag
    staleCartNoticeShown.current = true;
    const units = items.reduce((s: number, i: any) => s + (Number(i.quantity) || 1), 0);
    const countStr = `**${items.length} item${items.length !== 1 ? 's' : ''} (${units} unit${units !== 1 ? 's' : ''})**`;
    const when = age.label ? ` (last touched ${age.label})` : '';
    const content = age.suggest_clear
      ? `🛒 Heads up — your cart has ${countStr} carried over from an earlier session${when}. Say **"clear my cart"** to start fresh, or **"clear the old items but keep the latest"** to keep only what you just added — otherwise I'll factor it in.`
      : `🛒 Heads up — your cart has ${countStr}${when}. If some of that is stale, say **"clear my cart"** or **"clear the old items but keep the latest"**; otherwise I'll factor it in.`;
    setMessages(prev => [...prev, { role: 'assistant' as const, content, timestamp: new Date() }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatOpen, cart]);
  const [showLogin, setShowLogin] = useState(false);
  const [showAdminDash, setShowAdminDash] = useState(false);
  const [expandedLane, setExpandedLane] = useState<DeviceLane | null>(null);
  const [authUser, setAuthUser] = useState<{ email: string; name: string } | null>(() => getStoredAuthIdentity());

  // NQE history: tracks every question-option interaction for backend context
  const [nqeHistory, setNqeHistory] = useState<NqeInteraction[]>([]);
  const [confirmedSlots, setConfirmedSlots] = useState<Record<string, any>>({});

  // Multimodal: attached images queued for Send
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [attachedThumbs, setAttachedThumbs] = useState<string[]>([]);

  const filteredDisplayProducts = useMemo(() => {
    if (tierFilter === 'all') return displayProducts;
    const tierItems = tierFilter === 'lower'
      ? (rightPanelContract?.lower_tier?.items || [])
      : (rightPanelContract?.higher_tier?.items || []);
    if (!Array.isArray(tierItems) || tierItems.length === 0) return displayProducts;
    const bySku = new Map((displayProducts || []).map((p) => [String(p.sku), p] as const));
    return tierItems
      .map((p) => bySku.get(String((p as any)?.sku)) || (p as Product))
      .filter(Boolean);
  }, [tierFilter, rightPanelContract, displayProducts]);

  const laneBuckets = useMemo(() => {
    const out: Record<DeviceLane, Product[]> = {
      windows: [],
      macbook: [],
      tablet_chromebook: [],
    };
    for (const p of filteredDisplayProducts || []) {
      out[laneForProduct(p)].push(p);
    }
    return out;
  }, [filteredDisplayProducts]);

  const expandedLaneProducts = useMemo(
    () => (expandedLane ? (laneBuckets[expandedLane] || []) : []),
    [expandedLane, laneBuckets],
  );

  useEffect(() => {
    setExpandedLane(null);
  }, [rightPanelMode, filteredDisplayProducts]);

  useEffect(() => {
    setTierFilter('all');
  }, [displayProducts]);

  // Dual STT (browser + Whisper)
  const stt = useDualSTT({
    apiUrl: getApiBase(),
    apiKey: String((import.meta as any).env?.VITE_API_KEY || ''),
  });

  // Sync STT transcript into input
  useEffect(() => {
    if (stt.transcript) setInputValue(stt.transcript);
  }, [stt.transcript]);

  /** Add files from AttachmentButton / drop / paste */
  const handleAttach = useCallback((files: File[]) => {
    const imgFiles = files.filter(f => (
      f.type.startsWith('image/')
      || f.type === 'application/pdf'
      || f.type === 'text/plain'
      || /\.(?:pdf|txt)$/i.test(f.name)
    ));
    if (imgFiles.length === 0) return;
    setAttachedFiles(prev => [...prev, ...imgFiles]);
    // Generate thumbnails for images. Documents remain visible through their
    // filename in the upload/review response instead of a broken image preview.
    imgFiles.forEach(f => {
      if (!f.type.startsWith('image/')) return;
      const reader = new FileReader();
      reader.onload = () => setAttachedThumbs(prev => [...prev, reader.result as string]);
      reader.readAsDataURL(f);
    });
  }, []);

  const removeAttachment = useCallback((idx: number) => {
    setAttachedFiles(prev => prev.filter((_, i) => i !== idx));
    setAttachedThumbs(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const maybeAppendCvSecurityNote = (cvResult: any) => {
    if (!cvResult || typeof cvResult !== 'object') return;

    const tags = Array.isArray(cvResult.evidence_tags) ? cvResult.evidence_tags.map(String) : [];
    const ic = (cvResult.image_consistency && typeof cvResult.image_consistency === 'object') ? cvResult.image_consistency : null;

    const reasons = new Set<string>();
    try {
      const imgs = Array.isArray(ic?.images) ? ic.images : [];
      for (const it of imgs) {
        const rs = Array.isArray(it?.reasons) ? it.reasons : [];
        rs.forEach((r: any) => reasons.add(String(r)));
      }
    } catch {
      // ignore
    }

    const hasQr = tags.includes('qr_url_present') || tags.includes('ocr_prompt_injection') || reasons.has('qr_code_detected') || reasons.has('qr_external_url_detected') || Boolean(cvResult.qr_prompt_injection);
    const hasManipulation = tags.includes('manipulation_detected') || reasons.has('manipulation_detected');
    const hasPromptInjection = tags.includes('prompt_injection_text_suspected') || tags.includes('ocr_prompt_injection') || reasons.has('ocr_prompt_pattern_detected');
    if (!hasQr && !hasManipulation && !hasPromptInjection) return;

    const noteKey = String(cvResult.case_id || cvResult.trace_id || cvResult.decision_id || '') + `|qr=${hasQr}|manip=${hasManipulation}|pi=${hasPromptInjection}`;
    if (noteKey && noteKey === lastCvSecurityNoteKey) return;

    const parts: string[] = [];
    if (hasQr) parts.push('a QR code or external link');
    if (hasManipulation) parts.push('signs the photo may be edited or altered');
    if (hasPromptInjection && !hasQr) parts.push('embedded text that resembles an instruction or command');

    const what = parts.length === 2 ? `${parts[0]} and ${parts[1]}` : parts[0];
    const msg =
      `Security note: One of your photos appears to include ${what}.\n\n` +
      `For your safety, we do not follow links or accept photos with added overlays for verification. ` +
      `Please re-upload a new, unedited photo of the item and the damage (no stickers, text overlays, or QR codes).`;

    setLastCvSecurityNoteKey(noteKey || null);
    setMessages(prev => [...prev, { role: 'assistant', content: msg, timestamp: new Date() }]);
  };

  const refreshCart = async () => {
    try {
      const j = await getCart(uid);
      setCart(j);
    } catch {
      setCart(null);
    }
  };

  const addToCart = async (sku: string, qty: number = 1) => {
    if (!sku) return;
    // Bulk-order carry-through: if the CONVERSATION asked for N units ("15 work laptops") and this Add
    // came from a pick button (qty 1), land the conversation's quantity — via the sourcing-aware qty PUT
    // (allow_sourcing) so exceeding stock sources the shortfall instead of a silent 409. Fixes the demo's
    // "asked for 30, cart got 1".
    const bulkQty = qty <= 1 && pendingBulkQty && pendingBulkQty > 1 ? pendingBulkQty : null;
    if (bulkQty) {
      const picked = displayProducts.find((p) => p.sku === sku) || products.find((p) => p.sku === sku);
      const unitCents = Number((picked as any)?.price_cents)
        || Math.round(Number((picked as any)?.price || 0) * 100);
      const totalCents = Number((pendingBulkBudget as any)?.total_cents)
        || Math.round(Number((pendingBulkBudget as any)?.total || 0) * 100);
      const totalScope = String((pendingBulkBudget as any)?.scope || '').toLowerCase() === 'total';
      if (totalScope && totalCents > 0 && unitCents > 0 && bulkQty * unitCents > totalCents) {
        const affordable = Math.floor(totalCents / unitCents);
        const productName = picked?.name || sku;
        setChatOpen(true);
        setMessages((prev) => [...prev, {
          role: 'assistant' as const,
          content: 'That selection exceeds the preserved total budget. Nothing was added.',
          affordabilityResolution: {
            kind: 'total_budget_exceeded',
            sku,
            product_name: productName,
            currency: String((picked as any)?.currency || 'AUD'),
            requested_quantity: bulkQty,
            max_affordable_quantity: affordable,
            current_unit_price_cents: unitCents,
            cheaper_unit_price_max_cents: Math.floor(totalCents / bulkQty),
            budget_max_cents: totalCents,
            proposed_total_cents: bulkQty * unitCents,
            other_lines_total_cents: 0,
            choices: ['reduce_quantity', 'increase_budget', 'choose_cheaper_product'],
            requires_confirmation: true,
          },
          timestamp: new Date(),
        }]);
        return;
      }
      // Stale-cart preflight: disclose pre-existing lines (other SKUs) AT the moment of the bulk add,
      // so accumulated items from an earlier turn/session never surprise the buyer in the total.
      const priorOther = (cart?.items || []).filter((i: any) => i.sku && i.sku !== sku);
      const priorUnits = priorOther.reduce((s: number, i: any) => s + (Number(i.quantity) || 1), 0);
      await setCartQty(sku, bulkQty, true);
      setConfirmedSlots(prev => ({
        ...prev,
        exact_product_sku: sku,
        order_quantity: bulkQty,
        product_selection_authority: 'persisted_cart',
      }));
      setProcurementRequirements({});
      setSourcingIntent((intent) => sourcingIntentAfterSelection(intent, sku));
      switchRightPanelMode('cart');
      setChatOpen(true);
      const addedProduct = products.find((p) => p.sku === sku);
      const staleNote = priorOther.length > 0
        ? ` Your cart already had **${priorOther.length} other item${priorOther.length !== 1 ? 's' : ''} (${priorUnits} unit${priorUnits !== 1 ? 's' : ''})** from earlier — say **"clear my cart"** if you want just this.`
        : '';
      const bulkMsg = `Added **${bulkQty} × ${addedProduct?.name || sku}** to your cart (from your request). The delivery plan will show what ships locally, transfers from the network, or needs supplier sourcing.${staleNote}`;
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && last.content === bulkMsg) return prev;
        return [...prev, { role: 'assistant' as const, content: bulkMsg, timestamp: new Date() }];
      });
      emitConsumerSignal(uid, 'checkout', {});
      return;
    }
    try {
      const j = await addCartItem(uid, sku, Math.max(1, Math.floor(qty)));
      setCart(j);
      setConfirmedSlots(prev => ({
        ...prev,
        exact_product_sku: sku,
        order_quantity: Math.max(1, Math.floor(qty)),
        product_selection_authority: 'persisted_cart',
      }));
      setProcurementRequirements({});
      setSourcingIntent((intent) => sourcingIntentAfterSelection(intent, sku));
      // Track 2b — real conversion: add-to-cart is the demo storefront's terminal buy-intent action (no
      // separate checkout page), so it registers as a conversion for the session (de-duped per session →
      // one conversion regardless of how many items are added). Feeds the channel conversion-rate panel.
      emitConsumerSignal(uid, 'checkout', {});
      switchRightPanelMode('cart');
      // Proactive post-add message in the chat
      const addedProduct = products.find((p) => p.sku === sku);
      const productName = addedProduct?.name || sku;
      setChatOpen(true);
      const addMsg = `Nice choice! **${productName}** has been added to your cart. Want to see compatible accessories, or are you ready to checkout?`;
      setMessages((prev) => {
        // dedupe: a double-invoke (StrictMode / double-click) must not append the same line twice
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && last.content === addMsg) return prev;
        return [...prev, { role: 'assistant' as const, content: addMsg, timestamp: new Date() }];
      });
    } catch (e: any) {
      // Never fail silently: a stock-gate 409 previously showed nothing, so the buyer clicked Add and
      // got no feedback (and the planner then had no prior cart item). Surface WHY it was blocked.
      const addedProduct = products.find((p) => p.sku === sku);
      const productName = addedProduct?.name || sku;
      const m = String(e?.message || '');
      const outOfStock = /stock|409|insufficient|out_of_stock|available/i.test(m);
      const failMsg = outOfStock
        ? `I couldn't add **${productName}** — it's out of stock or the quantity exceeds what's available. Want me to find an in-stock alternative?`
        : `Sorry, I couldn't add **${productName}** to your cart just now. Please try again.`;
      setChatOpen(true);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && last.content === failMsg) return prev;
        return [...prev, { role: 'assistant' as const, content: failMsg, timestamp: new Date() }];
      });
    }
  };

  /** Open the chat and immediately send a query (used by filter buttons). */
  const openChatWithQuery = (query: string) => {
    setChatOpen(true);
    // Small delay so the panel finishes mounting before we fire the request
    setTimeout(() => handleSend({ queryOverride: query }), 80);
  };

  const removeFromCart = async (sku: string) => {
    if (!sku) return;
    try {
      const j = await removeCartItem(uid, sku);
      setCart(j);
    } catch {
      // ignore
    }
  };

  /** Cart stepper / multi-intent amendment — SET a line's absolute quantity. qty<=0 removes it.
   *  allowSourcing=true (from the multi-intent Confirm-qty) lets the line exceed stock; the shortfall is
   *  sourced at confirm-cart, so "15 instead" no longer 409s on a low-stock item. */
  const setCartQty = async (sku: string, qty: number, allowSourcing = false) => {
    if (!sku) return;
    try {
      const j = await setCartItemQty(uid, sku, qty, allowSourcing);
      setCart(j);
      // The cart write reports preferred-location stock, while the delivery planner also considers
      // network transfers. Do not claim supplier sourcing until that allocation has been computed.
      const sf = (j as any)?.sourcing_shortfall;
      if ((j as any)?.sourcing_required && sf && Number(sf.shortfall) > 0) {
        const nm = products.find((p) => p.sku === sku)?.name || sku;
        setChatOpen(true);
        setMessages((prev) => [...prev, { role: 'assistant' as const, timestamp: new Date(),
          // The cart write sees an admission stock snapshot; the split-offer
          // service owns location ATP, network transfers, and supplier
          // shortfall. Do not mislabel the snapshot as preferred-location ATP.
          content: `Set **${nm}** to ${sf.requested}. The delivery plan is recalculating the authoritative local, network-transfer, and supplier allocation; review and confirm that revised plan before checkout.` }]);
      }
    } catch (e: any) {
      // Never fail silently — surface WHY (out of stock / qty exceeds available), mirroring add-to-cart.
      const nm = products.find((p) => p.sku === sku)?.name || sku;
      const m = String(e?.message || '');
      const stockish = /stock|409|insufficient|out_of_stock|available/i.test(m);
      setChatOpen(true);
      setMessages((prev) => {
        const content = stockish
          ? `I couldn't set **${nm}** to that quantity — it's out of stock or exceeds what's available.`
          : `Sorry, I couldn't update **${nm}** just now. Please try again.`;
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && last.content === content) return prev;
        return [...prev, { role: 'assistant' as const, content, timestamp: new Date() }];
      });
    }
  };

  const clearCartAll = async () => {
    try {
      const j = await clearCart(uid, conversationEpoch);
      setCart(j);
      setPendingBulkQty(null);
      setPendingBulkBudget(null);
      setSourcingIntent(null);
      setFulfilmentCase(null);
      setBulkAlternatives([]);
      setProcurementRequirements({});
      setConfirmedSlots(prev => {
        const next = { ...prev } as Record<string, any>;
        for (const key of [
          'exact_product_sku', 'order_quantity', 'quantity',
          'total_budget_cents', 'budget_scope', 'product_selection_authority',
        ]) delete next[key];
        return next;
      });
      // Once the buyer explicitly clears, they own the cart — suppress the "previous session" stale
      // notice for the rest of the session so items they add next are never mislabeled as carried over.
      staleCartNoticeShown.current = true;
      initialCartSkus.current = [];   // nothing "previous" remains after a full clear
      // A cleared cart has no procurement story — release the sticky sourcing-trace pin so the Decision
      // Trace no longer resolves the (now-abandoned) bulk order's Procurement tab.
      setSourcingTraceId(null);
      setConfirmedSourcingOrderId(null);
    } catch {
      // ignore
    }
  };

  // UNDO a clear: re-add the items that were just removed — the reversible "put them back" for a buyer who
  // changed their mind. Sequential re-adds (the backend cart write is lock-free); the removal freed the
  // stock so they normally succeed. A since-sold-out line is skipped and reported, never silently dropped.
  const restoreClearedItems = async (items: { sku: string; quantity: number; name?: string }[]) => {
    let restored = 0;
    for (const it of items) {
      try {
        await addCartItem(uid, String(it.sku), Math.max(1, Math.floor(Number(it.quantity) || 1)));
        restored += 1;
      } catch {
        // keep going; partial restore is surfaced below
      }
    }
    const refreshed = await getCart(uid).catch(() => null);
    setCart(refreshed);
    staleCartNoticeShown.current = true;   // buyer is actively managing the cart — don't re-nag
    setMessages(prev => [...prev, { role: 'assistant' as const,
      content: restored === items.length
        ? `↩️ Restored ${restored} item(s) to your cart.`
        : `↩️ Restored ${restored} of ${items.length} item(s). The rest couldn't be re-added (likely now out of stock) — tell me what you need and I'll re-source them.`,
      timestamp: new Date() }]);
  };

  // V2 cart lane (C2): CONFIRM a proposed mutation plan → the transactional apply endpoint.
  // Every backend outcome is honest and rendered as such: applied (refresh + undo chip),
  // already_applied (a double-click / SSE retry — no second mutation happened), stale_cart
  // (the cart changed since the proposal — never applied), expired / rejected.
  const confirmCartPlan = async (msg: ChatMessage) => {
    const plan = msg.cartConfirm;
    if (!plan) return;
    // consume the card first so a double-click can't fire twice from the UI side either
    setMessages(prev => prev.map(m => m === msg ? { ...m, cartConfirm: undefined } : m));
    try {
      const out = await applyCartMutation(plan.planId, uid, undefined, conversationEpoch);
      const status = String(out.status || '');
      if (status === 'applied' || status === 'already_applied') {
        const destructive = (out.applied || []).some((a) =>
          ['clear_all', 'keep_only', 'remove_items', 'clear_previous'].includes(String(a.action)));
        const clearedAll = (out.applied || []).some((a) => String(a.action) === 'clear_all');
        const quantityChanged = (out.applied || []).some((a) =>
          String(a.action) === 'set_quantity');
        // The previous recommendation's fulfilment alternatives are quantity-specific. Once a
        // confirmed mutation changes the cart, only the refreshed delivery plan is authoritative.
        setBulkAlternatives([]);
        if (clearedAll) {
          setPendingBulkQty(null);
          setPendingBulkBudget(null);
          setSourcingIntent(null);
          setFulfilmentCase(null);
          setProcurementRequirements({});
          setSourcingTraceId(null);
          setConfirmedSourcingOrderId(null);
          staleCartNoticeShown.current = true;
          initialCartSkus.current = [];
          setConfirmedSlots(prev => {
            const next = { ...prev } as Record<string, any>;
            for (const key of [
              'exact_product_sku', 'order_quantity', 'quantity',
              'total_budget_cents', 'budget_scope', 'product_selection_authority',
            ]) delete next[key];
            return next;
          });
        }
        const refreshed = await getCart(uid).catch(() => null);
        setCart(refreshed);
        switchRightPanelMode('cart');
        setMessages(prev => [...prev, { role: 'assistant' as const,
          content: status === 'applied'
            ? quantityChanged
              ? 'Done — updated the cart quantity. Delivery and supplier allocations are quantity-specific, so review and confirm the revised plan; any earlier unsent RFQ draft will be superseded, not reused.'
              : '🧹 Done — applied the change to your cart.'
            : 'That change was already applied — your cart is up to date.',
          ...(status === 'applied' && destructive ? { undoServer: true } : {}),
          timestamp: new Date() }]);
      } else if (status === 'stale_cart') {
        setMessages(prev => [...prev, { role: 'assistant' as const,
          content: 'Your cart changed since I proposed that, so I didn\'t apply it (safety first). Tell me again what you\'d like and I\'ll redo it against the current cart.',
          timestamp: new Date() }]);
      } else if (status === 'expired') {
        setMessages(prev => [...prev, { role: 'assistant' as const,
          content: 'That confirmation window expired, so nothing was changed. Ask again and I\'ll set it up fresh.',
          timestamp: new Date() }]);
      } else if (status === 'conflict' && out.current_status === 'superseded') {
        setMessages(prev => [...prev, { role: 'assistant' as const,
          content: 'That plan was replaced by your newer cart instruction, so it cannot be applied. Your cart was not changed by the older plan.',
          timestamp: new Date() }]);
      } else {
        const error = (out as any)?.error;
        const err = error?.error || status || 'not applied';
        const resolution = error?.resolution?.kind === 'total_budget_exceeded'
          ? error.resolution as AffordabilityResolution
          : undefined;
        setMessages(prev => [...prev, { role: 'assistant' as const,
          content: resolution
            ? 'That quantity exceeds the preserved total budget. Nothing in your cart was changed.'
            : `I couldn't apply that (${err}) — nothing in your cart was changed.`,
          ...(resolution ? { affordabilityResolution: resolution } : {}),
          timestamp: new Date() }]);
      }
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant' as const,
        content: `I couldn't apply that change (${String(e?.message || e)}) — nothing in your cart was changed.`,
        timestamp: new Date() }]);
    }
  };

  const dismissCartPlan = async (msg: ChatMessage) => {
    const plan = msg.cartConfirm;
    if (!plan) return;
    setMessages(prev => prev.map(m => m === msg ? { ...m, cartConfirm: undefined } : m));
    try {
      const out = await rejectCartMutation(plan.planId, uid);
      const status = String(out.status || '');
      const content = status === 'rejected' || status === 'already_rejected'
        ? 'Okay — I discarded that plan and left your cart exactly as it was.'
        : `That plan was already ${String(out.current_status || status || 'closed')}; no cart change was made.`;
      setMessages(prev => [...prev, { role: 'assistant' as const, content, timestamp: new Date() }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant' as const,
        content: 'I could not durably discard that plan. I left your cart unchanged; please retry or send a newer instruction to supersede it.',
        timestamp: new Date() }]);
    }
  };

  const chooseAffordabilityResolution = (
    msg: ChatMessage,
    choice: AffordabilityResolution['choices'][number],
  ) => {
    const resolution = msg.affordabilityResolution;
    if (!resolution) return;
    setMessages(prev => prev.map(item => item === msg
      ? { ...item, affordabilityResolution: undefined }
      : item));
    const name = JSON.stringify(resolution.product_name);
    const budget = Math.round(resolution.budget_max_cents / 100);
    const proposed = Math.round(resolution.proposed_total_cents / 100);
    const query = choice === 'reduce_quantity'
      ? `Set ${name} to ${resolution.max_affordable_quantity} units and keep the total budget at $${budget}.`
      : choice === 'increase_budget'
        ? `Increase the total budget to $${proposed} and set ${name} to ${resolution.requested_quantity} units.`
        : `Show cheaper alternatives to ${name} that can supply ${resolution.requested_quantity} units within a total budget of $${budget}.`;
    void handleSend({ queryOverride: query });
  };

  // V2 cart lane: undo via the SERVER-side snapshot the transactional apply stashed
  // (survives reload; the same /cart/undo the clear button uses).
  const undoServerSnapshot = async (msg: ChatMessage) => {
    setMessages(prev => prev.map(m => m === msg ? { ...m, undoServer: undefined } : m));
    try {
      await undoCartClear(uid);
      const refreshed = await getCart(uid).catch(() => null);
      setCart(refreshed);
      setMessages(prev => [...prev, { role: 'assistant' as const,
        content: '↩️ Restored your cart from before that change.', timestamp: new Date() }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant' as const,
        content: `I couldn't restore the snapshot (${String(e?.message || e)}).`, timestamp: new Date() }]);
    }
  };

  // Snapshot the cart's SKUs on the FIRST cart read of the session: those are the "previous session"
  // items. Lets the cart offer "Clear previous (N)" — drop the carried-over items WITHOUT losing what
  // the buyer just added (the two-choice clear from the demo review). Empty first read → nothing is
  // ever labelled previous.
  const initialCartSkus = useRef<string[] | null>(null);
  useEffect(() => {
    let active = true;
    getCart(uid).then((j) => {
      if (!active) return;
      if (initialCartSkus.current === null) {
        initialCartSkus.current = (j?.items || []).map((i: any) => String(i.sku));
      }
      setCart(j);
    }).catch(() => {
      if (active && initialCartSkus.current === null) initialCartSkus.current = [];
    });
    return () => { active = false; };
  }, [uid]);
  useEffect(() => {
    if (initialCartSkus.current === null && cart) {
      initialCartSkus.current = (cart.items || []).map((i: any) => String(i.sku));
    }
  }, [cart]);
  const priorCartSkus = previousSessionSkus(
    (cart?.items || []).map((i: any) => String(i.sku)), initialCartSkus.current);
  const clearPriorCartItems = async () => {
    try {
      for (const sku of priorCartSkus) {
        await removeFromCart(sku);
      }
      const refreshed = await getCart(uid).catch(() => null);
      if (refreshed) setCart(refreshed);
      initialCartSkus.current = [];          // the carried-over set is gone; the rest is this session's
      staleCartNoticeShown.current = true;   // and no longer worth nagging about
    } catch {
      // best-effort — whatever was removed stays removed; Refresh shows the truth
    }
  };

  const handleCameraCapture = async (files: File[]) => {
    if (!files || files.length === 0) return;
    // Defer triage until Send — just attach thumbnails
    handleAttach(files);
    setCvPrefillImages(files);
  };

  // Microphone handler — delegates to dual STT hook
  const handleMicClick = () => {
    if (stt.error) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Speech recognition is not supported in your browser. Please try Chrome or Edge for voice input.',
        timestamp: new Date()
      }]);
      return;
    }
    stt.toggle();
  };

  const hasProcurementPanel = Boolean(fulfilmentCase);
  const hasRightPanel = rightPanelMode !== 'none' || hasProcurementPanel;
  // latest assistant turn's questions — used to detect a receipt/verification ask (not rendered as a
  // separate bottom bar anymore; NQE questions render inline in the message).
  const latestAssistantQuestions = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m?.role === 'assistant' && Array.isArray(m.nextQuestions) && m.nextQuestions.length > 0) {
        return m.nextQuestions.slice(0, 4);
      }
    }
    return [] as NonNullable<ChatMessage['nextQuestions']>;
  }, [messages]);
  const receiptRequested = useMemo(() => {
    return latestAssistantQuestions.some((q) => {
      const text = String(q?.text || '').toLowerCase();
      const goal = String(q?.goal || '').toLowerCase();
      return goal.includes('verify_purchase')
        || text.includes('receipt')
        || text.includes('order confirmation')
        || text.includes('serial number');
    });
  }, [latestAssistantQuestions]);

  const normalizeNextQuestions = (items: any[]): { id: string; text: string; goal?: string; why_hint?: string; options?: { id: string; label: string; value?: string }[] }[] => {
    if (!Array.isArray(items)) return [];
    const out = items
      .map((item: any, idx: number) => {
        if (item && typeof item === 'object') {
          const text = String(item.text || item.question || '').trim();
          if (!text) return null;
          const options = Array.isArray(item.options)
            ? item.options
                .map((o: any, j: number) => ({
                  id: String(o?.id || `opt_${j + 1}`),
                  label: String(o?.label || o?.text || '').trim(),
                  value: o?.value != null ? String(o.value) : undefined,
                }))
                .filter((o: any) => o.label)
                .slice(0, 5)
            : undefined;
          return {
            id: String(item.id || `nq_${idx + 1}`),
            text,
            goal: item.goal ? String(item.goal) : undefined,
            why_hint: item.why_hint ? String(item.why_hint) : undefined,
            options,
          };
        }
        const text = String(item || '').trim();
        if (!text) return null;
        return { id: `nq_${idx + 1}`, text };
      })
      .filter(Boolean) as { id: string; text: string; goal?: string; why_hint?: string; options?: { id: string; label: string; value?: string }[] }[];
    return out.slice(0, 3);
  };

  const formatNextQuestions = (items: any[]): string => {
    if (!Array.isArray(items) || items.length === 0) return '';
    const lines = items
      .map((item: any) => {
        if (item && typeof item === 'object') return String(item.text || item.question || '').trim();
        return String(item || '').trim();
      })
      .filter(Boolean)
      .slice(0, 3);
    if (lines.length === 0) return '';
    return `\n\nTo narrow this down quickly:\n- ${lines.join('\n- ')}`;
  };

  const complaintTextHint = (text: string) => /\b(return|broken|damaged|refund|complaint|defective|wrong item|warranty)\b/i.test(text || '');
  const visualSearchHint = (text: string) => /\b(find similar|similar products?|visual search|look like this|like this|match this)\b/i.test(text || '');

  const summarizeWhy = (items: Product[]) => {
    if (!Array.isArray(items) || items.length === 0) return '';
    const snippets = items
      .slice(0, 2)
      .map((p) => {
        const why = Array.isArray(p.why) ? p.why.filter(Boolean).slice(0, 2).map((w) => _prettyReason(String(w))) : [];
        const label = productShortLabel(p);
        if (!label || why.length === 0) return '';
        return `${label} (${why.join(', ')})`;
      })
      .filter(Boolean);
    return snippets.length > 0 ? `Top picks: ${snippets.join('; ')}.` : '';
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Lock body scroll when overlay is open
  useEffect(() => {
    if (chatOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [chatOpen]);

  // Lightweight backend liveness indicator (dev UX). Uses Vite proxy for /healthz.
  useEffect(() => {
    if (!chatOpen) return;
    let mounted = true;
    let iv: any = null;

    const ping = async () => {
      const ctl = new AbortController();
      const t0 = performance.now();
      const to = setTimeout(() => ctl.abort(), 10000);
      try {
        const r = await fetch(apiUrl('/healthz'), { signal: ctl.signal });
        const ms = Math.round(performance.now() - t0);
        if (!mounted) return;
        setBackendStatus({ ok: r.ok, latencyMs: ms, checkedAt: new Date(), error: r.ok ? null : `http_${r.status}` });
      } catch (e: any) {
        const ms = Math.round(performance.now() - t0);
        if (!mounted) return;
        setBackendStatus({ ok: false, latencyMs: ms, checkedAt: new Date(), error: e?.name === 'AbortError' ? 'timeout' : (e?.message || 'fetch_failed') });
      } finally {
        clearTimeout(to);
      }
    };

    ping();
    iv = setInterval(ping, 5000);
    return () => {
      mounted = false;
      if (iv) clearInterval(iv);
    };
  }, [chatOpen]);

  useEffect(() => {
    if (!chatOpen || !readinessOpen) return;
    let mounted = true;
    let iv: any = null;

    const pollReadyz = async () => {
      const ctl = new AbortController();
      const timeout = setTimeout(() => ctl.abort(), 2500);
      setReadyzLoading(true);
      try {
        const r = await fetch(apiUrl('/readyz'), { signal: ctl.signal });
        const data = await safeJson(r);
        if (!mounted) return;
        if (r.ok && data) setReadyz(data as ReadyzResponse);
      } catch {
        if (!mounted) return;
        setReadyz(null);
      } finally {
        clearTimeout(timeout);
        if (mounted) setReadyzLoading(false);
      }
    };

    pollReadyz();
    iv = setInterval(pollReadyz, 15000);
    return () => {
      mounted = false;
      if (iv) clearInterval(iv);
    };
  }, [chatOpen, readinessOpen]);

  const handleWhyProduct = async (sku: string) => {
    if (!sku || !traceId) return;
    setWhyDrawerSku(sku);
    setWhyDrawerData(null);
    setWhyDrawerError(null);
    setWhyDrawerLoading(true);
    try {
      const params = new URLSearchParams({ uid, sku, trace_id: traceId });
      const r = await fetch(apiUrl(`/api/v1/recommend/why_product?${params.toString()}`), {
        credentials: 'include',
        headers: { 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
      });
      const data = await safeJson(r);
      if (!r.ok || !data) throw new Error(`why_product_failed (${r.status})`);
      setWhyDrawerData((data.explanation || {}) as ProductWhyExplanation);
    } catch (e: any) {
      setWhyDrawerError(String(e?.message || 'Failed to load explanation'));
    } finally {
      setWhyDrawerLoading(false);
    }
  };

  const handleSend = async (opts?: { queryOverride?: string; nqeSelection?: { question_id: string; option_id: string; option_label: string; option_value?: string }; externalResearchConsent?: boolean }) => {
    const q = String(opts?.queryOverride ?? inputValue).trim();
    if (!q) return;
    try {
      localStorage.setItem('shopsquire_last_user_query', q);
    } catch {}

    // PII Detection - warn user and don't send sensitive data
    const pii = detectPII(q);
    if (pii) {
      const userMsg: ChatMessage = { role: 'user', content: q.replace(/\d/g, '*'), timestamp: new Date() };
      const warningMsg: ChatMessage = {
        role: 'assistant',
        content: `I noticed you may have entered a ${pii.type}. ${pii.advice}\n\nYour message was not sent to protect your privacy. Please rephrase without sensitive information.`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, userMsg, warningMsg]);
      setInputValue('');
      return;
    }

    // N3 Mode-B: an explicit web-search imperative is a CONSENT REQUEST, not a command — the fetch
    // only happens if the buyer clicks the chip (which re-sends WITH external_research_consent).
    // This is simultaneously the UX and the trigger-forcing mitigation: prompt-crafted imperatives
    // cannot make the platform touch the network.
    if (opts?.externalResearchConsent === undefined   // chip answers (true OR false) bypass — no loop
        && requiresExternalResearchConsent(q)) {
      setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
        { role: 'assistant',
          content: 'I can check an APPROVED external source for that (curated allowlist, nothing about you or your order is sent). Want me to?',
          webConsentPrompt: { query: q },
          timestamp: new Date() }]);
      setInputValue('');
      return;
    }
    // CART ACTIONS the assistant can genuinely do — executed client-side against the real cart API, with
    // an honest confirmation ("clear my cart" used to silently do nothing; the demo's top complaint).
    // SCOPED clear first: "clear the old items from the previous session" — drop ONLY the carried-over
    // items, keep what was added this session. Checked before the full clear (phrases like "clear the old
    // items in my cart" match both) and does NOT require the word "cart" (the live miss: this phrasing
    // fell through to product search).
    // KEEP-scoped clear: "clear the cart but keep the latest / this one / the ThinkPad" → remove everything
    // EXCEPT the item to keep. Distinct from "clear the OLD items", and MUST be caught before BOTH the
    // old-items scoped clear and the full clear below — otherwise "clear cart but keep the latest" falls
    // through to clearCartAll() and wipes the very item the buyer asked to keep (the live recording bug).
    // When the keep intent is clear but WHICH item is ambiguous, we ASK rather than clear anything — the
    // one thing we must never do is guess-then-wipe.
    {
      const keepRes = keepAfterClear(q, (cart?.items as any[]) || [], initialCartSkus.current);
      if (keepRes.isKeepClear) {
        const items = (cart?.items as any[]) || [];
        if (items.length === 0) {
          setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
            { role: 'assistant', content: 'Your cart is already empty — nothing to keep or clear.', timestamp: new Date() }]);
          setInputValue(''); switchRightPanelMode('cart'); return;
        }
        if (keepRes.keepSkus.length === 0) {
          setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
            { role: 'assistant', content: 'I can clear the cart but keep one item — which should I keep? Name it (or say "keep the latest") and I\'ll remove the rest.', timestamp: new Date() }]);
          setInputValue(''); switchRightPanelMode('cart'); return;
        }
        const keepSet = new Set(keepRes.keepSkus.map(String));
        const toRemove = items.filter((i) => !keepSet.has(String(i.sku)));
        // SEQUENTIAL, not Promise.all — the backend cart remove is a lock-free read-modify-write
        // (cart.py remove_item); parallel deletes race and silently leave an item behind.
        for (const it of toRemove) {
          await removeCartItem(uid, String(it.sku)).catch(() => null);
        }
        const refreshed = await getCart(uid).catch(() => null);
        setCart(refreshed);
        const keptItem = items.find((i) => keepSet.has(String(i.sku)));
        const keptName = (keptItem && productShortLabel(keptItem as any)) || keepRes.keepSkus[0];
        setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
          { role: 'assistant', content: `🧹 Done — removed ${toRemove.length} item(s) and kept **${keptName}**. That's what's left in your cart.`,
            undoClear: { items: toRemove.map((i) => ({ sku: String(i.sku), quantity: Number(i.quantity) || 1, name: i.name })) },
            timestamp: new Date() }]);
        setInputValue(''); switchRightPanelMode('cart'); return;
      }
    }
    if (/\b(?:clear|remove|delete|drop|get\s+rid\s+of)\b.{0,40}\b(?:old|previous|prior|earlier)\b.{0,40}\b(?:items?|units?|session|cart|stuff)\b/i.test(q)) {
      // The buyer can ask this before the first cart refresh has populated `initialCartSkus`.
      // In that case, read the backend cart now and treat those already-present lines as the
      // carried-over set; otherwise the phrase falsely replies "nothing carried" and leaves
      // stale items in place.
      const latestCart = cart || await getCart(uid).catch(() => null);
      const currentSkus = (latestCart?.items || []).map((i: any) => String(i.sku)).filter(Boolean);
      if (initialCartSkus.current === null) initialCartSkus.current = currentSkus;
      const carriedSkus = priorCartSkus.length > 0 ? priorCartSkus : previousSessionSkus(currentSkus, initialCartSkus.current);
      const n = carriedSkus.length;
      // Capture the removed lines BEFORE deleting, so the Undo chip can put them back.
      const carriedSet = new Set(carriedSkus.map(String));
      const removedItems = (latestCart?.items || []).filter((i: any) => carriedSet.has(String(i.sku)))
        .map((i: any) => ({ sku: String(i.sku), quantity: Number(i.quantity) || 1, name: i.name }));
      if (n > 0) {
        if (carriedSkus.length === currentSkus.length) {
          await clearCart(uid).catch(() => null);
        } else {
          // SEQUENTIAL, not Promise.all: the backend cart remove is a read-modify-write with no lock
          // (cart.py remove_item), so parallel deletes race — two concurrent removes both read the same
          // cart and the second save clobbers the first, silently leaving one item behind. Awaiting each
          // in turn is correct; a few extra round-trips on a handful of items is negligible.
          for (const sku of carriedSkus) {
            await removeCartItem(uid, sku).catch(() => null);
          }
        }
        const refreshed = await getCart(uid).catch(() => null);
        setCart(refreshed);
        initialCartSkus.current = [];
        staleCartNoticeShown.current = true;
      }
      setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
        { role: 'assistant', content: n > 0
            ? `🧹 Done — removed the ${n} item(s) carried over from your previous session. Everything you added this session is still in the cart.`
            : 'There are no items carried over from a previous session — everything in the cart was added this session. Say "clear my cart" if you want to start completely fresh.',
          ...(n > 0 && removedItems.length ? { undoClear: { items: removedItems } } : {}),
          timestamp: new Date() }]);
      setInputValue('');
      switchRightPanelMode('cart');
      return;
    }
    if (/\b(?:clear|empty|wipe|reset)\b.{0,20}\bcart\b|\bcart\b.{0,12}\b(?:clear|empty)\b/i.test(q)) {
      // Capture the whole cart BEFORE the wipe so the Undo chip can restore it.
      const removedItems = ((cart?.items as any[]) || []).map((i) => ({ sku: String(i.sku), quantity: Number(i.quantity) || 1, name: i.name }));
      setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
        { role: 'assistant', content: '🧹 Done — your cart is now empty. Tell me what you need and I\'ll help you rebuild it.',
          ...(removedItems.length ? { undoClear: { items: removedItems } } : {}),
          timestamp: new Date() }]);
      setInputValue('');
      await clearCartAll();
      switchRightPanelMode('cart');
      return;
    }
    // HONEST REFUSAL + capability-gap ledger: actions the assistant genuinely can't execute yet get a
    // truthful "not yet" (never silence), and the ask is RECORDED so QA can mine the ledger for the
    // roadmap — a bounded platform getting smarter without getting looser.
    const unsupported = (
      // cancel / refund / return (with or without the literal "order": "I want a refund", "refund me",
      // "money back", "cancel it/my purchase/subscription", "return this")
      /\b(?:cancel|refund|return)\b.{0,24}\b(?:order|purchase|subscription|it|this)\b|\b(?:refund|money\s+back)\b|\bcancel\s+(?:it|this|that|my)\b/i.exec(q)
      // order status / tracking ("where is my order", "order status", "has it shipped", "when will it arrive")
      || (isUnsupportedPostPurchaseTracking(q) ? [q] : null)
      // change/update address, payment, or contact info
      || /\b(?:change|update|edit)\b.{0,24}\b(?:address|shipping|delivery\s+address|payment|card|email|phone)\b/i.exec(q)
      // vouchers / promo / gift cards ("apply/use/redeem/enter my coupon", "promo code", "gift card")
      || /\b(?:apply|use|redeem|enter|add|have)\b.{0,20}\b(?:coupon|voucher|discount\s+code|promo(?:\s+code)?|gift\s+card)\b|\bpromo\s+code\b|\bgift\s+card\b/i.exec(q)
    );
    if (unsupported) {
      setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
        { role: 'assistant', content: `I can't do that from chat yet ("${unsupported[0]}") — a human teammate can via the admin console. I've logged your request so we prioritize building it. Meanwhile I can help you find products, manage cart quantities, or plan a bulk order.`, timestamp: new Date() }]);
      setInputValue('');
      try {
        fetch(apiUrl('/api/v1/consumer/capability-gap'), {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || '') },
          body: JSON.stringify({ utterance: q, category: 'unsupported_action', refusal_reason: 'chat_action_not_implemented', surface: 'chat', uid }),
        }).catch(() => {});
      } catch { /* ledger is best-effort */ }
      return;
    }

    // BARE price objection ("too expensive", "over my budget") with no search/budget cue → a governed,
    // margin-SAFE value reframe (never an invented discount): value-first, offer lower-priced in-budget
    // options, and the honest escalation path (a human-approved volume discount that stays within pricing
    // policy — never below the margin floor). "too expensive, show cheaper / under $1500" is NOT caught —
    // that carries a search cue and routes to a normal (cheaper) search.
    if (/\b(?:too\s+(?:expensive|much|pricey|dear|costly)|over\s+(?:my\s+)?budget|can'?t\s+afford|out\s+of\s+(?:my\s+)?budget|way\s+too\s+much|bit\s+(?:pricey|steep))\b/i.test(q)
        && !/\b(?:show|find|cheaper|lower|under|below|instead|options?|alternatives?|else|other|what\s+about)\b|\$\s?\d|\b\d{3,}\b/i.test(q)) {
      setMessages(prev => [...prev, { role: 'user', content: q, timestamp: new Date() },
        { role: 'assistant', content:
          "I hear you — price matters. These picks lead on value: warranty, longevity, and total cost of "
          + "ownership, not just the sticker. If your budget's firm, tell me your cap and I'll show lower-priced "
          + "options that still cover what you need. For a larger or bulk order I can also flag a volume discount "
          + "for a teammate to approve — I keep any pricing within policy and never below our margin floor. "
          + "Want me to show cheaper options, or set a budget?",
          timestamp: new Date() }]);
      setInputValue('');
      return;
    }

    const userMsg: ChatMessage = {
      role: 'user', content: q, timestamp: new Date(), images: [...attachedThumbs], voiceUsed: stt.source !== null,
      ...(opts?.nqeSelection ? { nqeSelection: { questionId: opts.nqeSelection.question_id, questionText: '', optionId: opts.nqeSelection.option_id, optionLabel: opts.nqeSelection.option_label, optionValue: opts.nqeSelection.option_value, ts: Date.now() } } : {}),
    };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');
    const currentAttachedFiles = [...attachedFiles];
    const currentSttConf = stt.whisperConfidence;
    const currentSttSrc = stt.source;
    setAttachedFiles([]);
    setAttachedThumbs([]);
    // Render a local acknowledgement before authentication, preflight, or an occupied
    // inference lane can delay the first SSE frame. This is deliberately non-authoritative:
    // it confirms receipt only and never claims that retrieval, fit, ATP, or mutation ran.
    const acknowledgedSku = String(
      (confirmedSlots as any)?.exact_product_sku
      || (confirmedSlots as any)?.canonical_sku
      || (confirmedSlots as any)?.sku
      || '',
    ).trim();
    setStreamAcknowledgement(
      acknowledgedSku
        ? `Request understood. Keeping ${acknowledgedSku} while I check the current case…`
        : 'Request understood. Checking the current case without changing it…',
    );
    setIsThinking(true);

    const mode = detectPanelMode(q);
    const shoppingIntent = isShoppingIntentQuery(q);
    const cartUpsellIntent = isCartUpsellIntentQuery(q) && ((cart?.items || []).length > 0);
    const complaintIntent = isComplaintIntent(q);
    const hasImages = currentAttachedFiles.length > 0;
    const hasPendingImage = Boolean(pendingImageContext) || cvPrefillImages.length > 0 || hasImages;
    const explicitVisualIntent = visualSearchHint(q);
    const explicitComplaintIntent = complaintTextHint(q);
    const requestImageContext = (Boolean(pendingImageContext) && !explicitComplaintIntent) ? pendingImageContext : null;
      const imageRecommendationTurn = hasImages || Boolean(requestImageContext);
      const textEvidenceIntent = hasImages && (
        /\b(?:can\s+you\s+read|read\s+(?:this|it)|ocr|requirements?|spec(?:ification)?s?|document|screenshot)\b/i.test(q)
        || currentAttachedFiles.some((file) =>
          /\b(?:ocr|requirements?|specs?|document|screenshot)\b/i.test(
            file.name.replace(/[-_]+/g, ' '),
          )
        )
      );
    if (imageRecommendationTurn) {
      setCanonicalImageProducts(null);
      setCanonicalImageSummary('');
    }

    if (hasPendingImage && explicitComplaintIntent && !hasImages) {
      setPendingImageContext(null);
      switchRightPanelMode('cv');
      setCvAutoIssueType(detectCVIssueType(q));
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Opening return/complaint flow with your uploaded photo.',
        timestamp: new Date(),
      }]);
      setIsThinking(false);
      return;
    }

    if (requestImageContext) {
      setPendingImageContext(null);
      if (explicitVisualIntent) {
        setCvPrefillImages([]);
      }
    }

    // Call backend
    try {
      // Open-vocabulary ambiguous requests take a fast, deterministic lane first. This creates
      // the durable shopping case, provisional shelves, high-information question, and zero-call
      // trace without waiting for an LLM/provider. A 204 means the request belongs to the normal
      // local catalogue/chat path below. The browser supplies only the buyer's words; research
      // hypotheses and publisher scope are server-owned.
      if (
        !activeShoppingCase?.case_id
        && !hasImages
        && !complaintIntent
        && !explicitComplaintIntent
        && mode !== 'faq'
      ) {
        const interpretationResponse = await fetch(apiUrl('/api/v1/shopping-cases/interpretations'), {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
            ...csrfHeaders(),
          },
          body: JSON.stringify({ uid, retained_purpose: q }),
        });
        if (interpretationResponse.status !== 204) {
          const interpretation = await safeJson(interpretationResponse);
          if (!interpretationResponse.ok || !interpretation) {
            throw new Error(String(
              interpretation?.detail?.message
              || interpretation?.detail?.code
              || interpretation?.detail
              || `case_interpretation_failed (${interpretationResponse.status})`,
            ));
          }
          if (interpretation?.ambiguity_exploration?.schema_version === 'ambiguity-exploration-v1') {
            // A new case owns the right panel. Do not leave the prior turn's
            // catalog cards actionable underneath provisional case shelves.
            setDisplayProducts([]);
            setRecommendationShelf(null);
            setSourcingIntent(null);
            setFulfilmentCase(null);
            setSourcingTraceId(null);
            setPendingBulkQty(null);
            setPendingBulkBudget(null);
            setAmbiguityExploration(interpretation.ambiguity_exploration as AmbiguityExploration);
            setActiveShoppingCase({
              case_id: String(interpretation.ambiguity_exploration.case_id),
              retained_purpose: String(interpretation.ambiguity_exploration.retained_purpose || q),
            });
          }
          if (interpretation?.product_shelves?.schema_version === 'product-shelves-v1') {
            setProductShelves(interpretation.product_shelves as ProductShelfProjection);
          }
          setTraceId(normalizeTraceId(interpretation.trace_id || interpretation.case_id || null));
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: String(interpretation.assistant_message || 'I opened a provisional research case.'),
            timestamp: new Date(),
          }]);
          switchRightPanelMode('grid');
          return;
        }
      }

      // If images are attached, triage them first
      let imageTriageResults: any[] = [];
      if (hasImages) {
        if (complaintIntent || explicitComplaintIntent || mode === 'faq') {
          setCvPrefillImages(currentAttachedFiles);
          switchRightPanelMode(mode === 'faq' ? 'faq' : 'cv');
          setCvAutoIssueType(detectCVIssueType(q));
          const lowerQ = q.toLowerCase();
          const fallbackAnswer = /return|refund|warranty|replace|exchange/.test(lowerQ)
            ? 'I opened the return/complaint flow. You can start the claim now; image security and damage triage will continue in the background so the policy answer is not blocked.'
            : 'I opened the support flow for this device issue. I will keep the uploaded image under review in the background while you continue.';
          const supportAnswer = await fetchSupportAnswer(q);
          const answer = supportAnswer || fallbackAnswer;
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: answer,
            timestamp: new Date(),
          }]);
          setImageRoutingInFlight(false);
          window.setTimeout(() => void (async () => {
            try {
              const deepResults = await fetchImageTriages(currentAttachedFiles, false);
              if (!Array.isArray(deepResults) || deepResults.length === 0) return;
              setImageTriageContexts(toImageTriageContexts(deepResults, currentAttachedFiles));
              setImageTriageRaw(deepResults);
            } catch {
              // Support/FAQ answer is intentionally independent of deep image triage.
            }
          })(), IMAGE_DEEP_TRIAGE_DELAY_MS);
          setIsThinking(false);
          return;
        }
        setImageRoutingInFlight(true);
        try {
          // Return the admission verdict quickly, then run the deeper visual and
          // security inspection independently. Pending evidence is never trusted
          // for ranking or commercial authority; the server-side gate remains the
          // enforcement boundary while the UI can continue read-only assistance.
          if (textEvidenceIntent) {
            // A requirements/document upload must wait for bounded OCR; sending the
            // fast filename-only result would erase the very evidence the buyer asked
            // us to read before /chat/query is constructed.
            imageTriageResults = await fetchImageTriages(currentAttachedFiles, false, true);
            if (!imageTriageResults.some((row: any) => (
              typeof row?.extracted_text === 'string' && row.extracted_text.trim().length >= 12
            ))) {
              // OCR/provider startup can occasionally return a valid but empty
              // first result. Retry this free local evidence step once; never
              // turn an empty extraction into a knowledge or product-fit claim.
              const retryResults = await fetchImageTriages(currentAttachedFiles, false, true);
              if (retryResults.some((row: any) => (
                typeof row?.extracted_text === 'string' && row.extracted_text.trim().length >= 12
              ))) {
                imageTriageResults = retryResults;
              }
            }
          } else {
            imageTriageResults = await fetchImageTriages(currentAttachedFiles, true);
            void fetchImageTriages(currentAttachedFiles, false).then((deepResults) => {
              if (!Array.isArray(deepResults) || deepResults.length === 0) return;
              setImageTriageContexts(toImageTriageContexts(deepResults, currentAttachedFiles));
              setImageTriageRaw(deepResults);
              const deepTraceId = deepResults.find((row: any) => (
                row?.decision_trace_id || row?.trace_id || row?.decision_id || row?.artifact?.artifact_id
              ));
              setTraceId(normalizeTraceId(
                deepTraceId?.decision_trace_id
                  || deepTraceId?.trace_id
                  || deepTraceId?.decision_id
                  || deepTraceId?.artifact?.artifact_id
                  || null,
              ));
            }).catch(() => {
              // The typed fast result remains visible as pending/degraded. A deep
              // inspection failure must not silently promote the attachment.
            });
          }
        } finally {
          setImageRoutingInFlight(false);
        }

        const unusableImageEvidence = imageTriageResults.filter(isUnusableImageEvidence);
        if (unusableImageEvidence.length > 0) {
          const pendingTraceId = imageTriageResults.find((row: any) => row?.artifact?.artifact_id);
          setTraceId(normalizeTraceId(pendingTraceId?.artifact?.artifact_id || null));
          const contexts = toImageTriageContexts(imageTriageResults, currentAttachedFiles);
          setImageTriageContexts(contexts);
          setImageTriageRaw(imageTriageResults);
          setDisplayProducts([]);
          setRecommendationShelf(null);
          setCanonicalImageProducts([]);
          setCanonicalImageSummary(
            'No product recommendation was produced because this attachment is not yet trusted evidence.',
          );
          switchRightPanelMode('visual_search');
          setVisualSearchQuery(q);
          const degraded = unusableImageEvidence.some((result: any) => (
            Boolean(result?._upload_error)
            || String(result?.artifact?.state || result?.security?.artifact_state || '').toLowerCase() === 'degraded'
          ));
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: degraded
              ? 'Attachment analysis degraded. It was not used for recommendations, memory, or commercial actions. You can retry or continue with text-only specifications.'
              : 'Attachment inspection is still under review. It was not used for recommendations, memory, or commercial actions. The deeper security result will remain attached to this turn.',
            timestamp: new Date(),
          }]);
          setIsThinking(false);
          return;
        }

        // Auto-route to CV if damage detected
        const anyDamage = imageTriageResults.some((t: any) => {
          const ds = t?.damage_score ?? 0;
          return ds >= 0.7;
        });
        if (anyDamage && (explicitComplaintIntent || complaintIntent)) {
          setCvPrefillImages(currentAttachedFiles);
          switchRightPanelMode('cv');
          setCvAutoIssueType(detectCVIssueType(q));
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: 'I detected likely damage in your photo and opened the return/complaint panel.',
            timestamp: new Date(),
          }]);
          setIsThinking(false);
          return;
        }

        // Shopping intent with images (no damage): switch to visual_search panel
        if (!anyDamage && imageTriageResults.length > 0 && !complaintIntent && !explicitComplaintIntent) {
          const triageCtxs = toImageTriageContexts(imageTriageResults, currentAttachedFiles);
          setImageTriageContexts(triageCtxs);
          setImageTriageRaw(imageTriageResults);
          switchRightPanelMode('visual_search');
          setVisualSearchQuery(q);

          // Product selection always continues through /chat/query. The visual panel is a
          // renderer for that canonical slate; it no longer owns an independent /suggest call.
        }
      }

      const routeToComplaint = shouldRouteToComplaint({
        mode, complaintIntent, explicitComplaintIntent, shoppingIntent,
        damageSignal: hasDamageSignal(q), hasImages,
        explicitVisualIntent, hasImageContext: Boolean(requestImageContext),
      });
      if (routeToComplaint) {
        const r = await fetch(apiUrl('/api/v1/orchestrate'), {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            ...csrfHeaders(),
            'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
          },
          body: JSON.stringify({
            uid: getOrCreateStoredUid(),
            cart_total_cents: 0,
            query: q,
            complaint_intent: true,
          }),
        });
        const data = await safeJson(r);
        if (!r.ok || !data) {
          throw new Error((data && data.detail) ? data.detail : `orchestrate_failed (${r.status})`);
        }

        const unusableUploads = imageTriageResults.filter((t: any) =>
          Boolean(t?._upload_error) || ['pending', 'degraded', 'quarantined', 'superseded'].includes(
            String(t?.artifact?.state || t?.security?.artifact_state || '')
          )
        );
        if (unusableUploads.length > 0) {
          const names = unusableUploads.map((t: any) => String(t?._filename || t?.filename || 'attachment')).join(', ');
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: `Attachment security notice: ${names} ${unusableUploads.length === 1 ? 'was' : 'were'} not used for image-derived recommendations. Read-only text assistance may continue, but commercial actions remain blocked for this evidence.`,
            timestamp: new Date(),
          }]);
        }
        mergeTrustEvidence(data);
        const proposal = data.proposal || {};
        const results = (proposal.results || []) as any[];
        const prods = results.map((item) => {
          const price = item.price_cents ? item.price_cents / 100 : item.price;
          const specs = item.specs || {};
          const features = [
            specs.cpu,
            specs.ram_gb ? `${specs.ram_gb}GB RAM` : undefined,
            specs.storage,
            specs.display,
            specs.wifi,
          ].filter(Boolean) as string[];
          return {
            sku: item.sku,
            name: item.name,
            price: price ?? 0,
            features,
            image_url: item.image_url,
            // Preserve backend signals this field-by-field map used to drop (stock honesty + why).
            why: item.why,
            score_norm: item.score_norm,
            stock_status: item.stock_status,
            stock_level: item.stock_level,
            stock_urgency: item.stock_urgency,
            cart_eligible: item.cart_eligible,
          } as Product;
        });
        setTraceId(normalizeTraceId(data.decision_trace_id || data.trace_id || proposal.trace_id || null));
        if (prods.length > 0) {
          setDisplayProducts(prods);
          switchRightPanelMode('cv');
          setCvAutoIssueType(detectCVIssueType(q));
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: `I've started a return review. I also found ${prods.length} related items if you want comparisons.`,
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else {
          switchRightPanelMode('cv');
          setCvAutoIssueType(detectCVIssueType(q));
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: "I've started a return review. Please add photos if you have them.",
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, assistantMsg]);
        }
      } else {
        // Build multimodal chat payload
        const chatPayload: any = {
          uid,
          query: q,
          session_id: conversationEpoch,
          memory_mode: temporaryChat ? 'temporary' : 'standard',
        };
        if (activeShoppingCase?.case_id || ambiguityExploration?.case_id) {
          chatPayload.shopping_case_id = activeShoppingCase?.case_id || ambiguityExploration?.case_id;
        }
        const copyProfileId = String(localStorage.getItem('shopsquire_copy_profile_id') || (import.meta as any).env?.VITE_COPY_PROFILE_ID || '').trim();
        const copyBrandName = String(localStorage.getItem('shopsquire_brand_name') || (import.meta as any).env?.VITE_BRAND_NAME || '').trim();
        const copyEnabled =
          String(localStorage.getItem('shopsquire_copywriting_enabled') || (import.meta as any).env?.VITE_COPYWRITING_ENABLED || '0')
            .trim()
            .toLowerCase() === '1' || String(localStorage.getItem('shopsquire_copywriting_enabled') || '').trim().toLowerCase() === 'true';
        if (copyEnabled) chatPayload.copywriting_enabled = true;
        if (copyProfileId) chatPayload.copy_profile_id = copyProfileId;
        if (copyBrandName) chatPayload.brand_name = copyBrandName;
        chatPayload.copy_surface = 'storefront';
        if (opts?.externalResearchConsent) chatPayload.external_research_consent = true;
        if (opts?.nqeSelection) {
          chatPayload.nqe_selection = opts.nqeSelection;
        }
        if (currentSttSrc) {
          chatPayload.voice_transcript = q;
          chatPayload.voice_confidence = currentSttConf ?? undefined;
        }
        // Attach image triage data
        if (imageTriageResults.length > 0) {
          chatPayload.images = imageTriageResults.map((t: any) => {
            const productIdentity = t?.product_identity || null;
            const artifactState = String(t?.artifact?.state || t?.security?.artifact_state || '').toLowerCase();
            const trustedImageEvidence = artifactState === 'clean'
              && t?.provider !== 'client_fast_boundary'
              && (t?.is_product_photo === true || Boolean(productIdentity));
            const trustedOcrEvidence = artifactState === 'clean'
              && t?.provider !== 'client_fast_boundary'
              && typeof t?.extracted_text === 'string'
              && t.extracted_text.trim().length > 0;
            return {
              // Do not pass filename-derived fast labels into /chat/query; names like
              // apple-red.jpg can otherwise look like product intent and bias ranking.
              labels: trustedImageEvidence && Array.isArray(t?.labels) ? t.labels : [],
              ocr_text: trustedOcrEvidence ? t.extracted_text : '',
              image_hash: t?.image_hash || null,
              product_identity: productIdentity,
              damage_score: t?.damage_score ?? 0,
              is_product_photo: trustedImageEvidence,
              intent_routing: t?.intent_routing || null,
              security: t?.security || null,
            };
          });
        } else if (requestImageContext) {
          chatPayload.image_labels = requestImageContext.labels || [];
          chatPayload.image_ocr_text = requestImageContext.ocrText || '';
          chatPayload.image_hash = requestImageContext.imageHash || undefined;
          if ((requestImageContext as any).productIdentity) {
            chatPayload.image_product_identity = (requestImageContext as any).productIdentity;
          }
          chatPayload.image_intent = 'visual_search';
        }
        chatPayload.recent_messages = messages.slice(-6).map(m => {
          const entry: any = { role: m.role, content: m.content };
          if (m.nqeSelection) entry.nqe_selection = m.nqeSelection;
          if (m.nqeSelectionApplied) entry.nqe_selection_applied = m.nqeSelectionApplied;
          if (m.nextQuestions && m.nextQuestions.length > 0) {
            entry.nqe_questions_shown = m.nextQuestions.map(nq => nq.id);
          }
          return entry;
        });
        if (nqeHistory.length > 0) {
          chatPayload.nqe_history = nqeHistory.slice(-10);
        }
        if (confirmedSlots && Object.keys(confirmedSlots).length > 0) {
          chatPayload.confirmed_slots = confirmedSlots;
        }

        // ONE idempotency key per send, shared by BOTH the stream and the /chat/query fallback
        // (review-6 #11): a slow first turn + the fallback must not double-serve/double-resolve.
        const idempotencyKey = ((globalThis as any).crypto?.randomUUID?.())
          || `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const apiHeaders = {
          'Content-Type': 'application/json',
          ...csrfHeaders(),
          'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
          // canonical header the backend single-flight reads (review-7 P0 — name now matches)
          'Idempotency-Key': idempotencyKey,
        };
        // SSE deadlines (review-6 #11): the connect timeout only aborts if headers are slow; the
        // body read loop needs its OWN idle + total deadlines or a hung server stalls forever
        // (the `thinking` event arrives instantly, resolving fetch and clearing the old timer).
        // Local/browser CORS setup can spend ~3s in middleware + preflight before streaming
        // headers arrive. A 3.5s cutoff raced healthy streams and started a duplicate fallback
        // that merely waited on the same idempotent producer. Heartbeat/idle/total limits below
        // still bound execution; this deadline only allows the connection to become established.
        const _SSE_CONNECT_MS = 10000;
        const _SSE_IDLE_MS = 20000;     // no chunk for 20s → server hung, abort → fallback
        const _SSE_TOTAL_MS = 90000;    // whole-turn ceiling
        const tryStreamChat = async (): Promise<any | null> => {
          const ctl = new AbortController();
          const connectTimer = setTimeout(() => ctl.abort(), _SSE_CONNECT_MS);
          const totalTimer = setTimeout(() => ctl.abort(), _SSE_TOTAL_MS);
          let idleTimer: ReturnType<typeof setTimeout> | null = null;
          const armIdle = () => { if (idleTimer) clearTimeout(idleTimer); idleTimer = setTimeout(() => ctl.abort(), _SSE_IDLE_MS); };
          const clearAll = () => { clearTimeout(connectTimer); clearTimeout(totalTimer); if (idleTimer) clearTimeout(idleTimer); };
          let resp: Response;
          try {
            resp = await fetch(apiUrl('/api/v1/chat/stream'), {
              method: 'POST',
              credentials: 'include',
              headers: apiHeaders,
              body: JSON.stringify(chatPayload),
              signal: ctl.signal,
            });
          } finally {
            clearTimeout(connectTimer);   // headers arrived (or aborted) — idle/total now govern
          }
          if (!resp.ok || !resp.body) { clearAll(); return null; }
          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let answerPayload: any = null;
          try {
          armIdle();   // start the idle watch now that we're reading the body
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            armIdle();   // a chunk arrived — reset the idle deadline
            buffer += decoder.decode(value, { stream: true });
            buffer = buffer.replace(/\r\n/g, '\n');
            let splitIdx = buffer.indexOf('\n\n');
            while (splitIdx >= 0) {
              const frame = buffer.slice(0, splitIdx);
              buffer = buffer.slice(splitIdx + 2);
              const lines = frame.split('\n');
              let eventName = 'message';
              const dataLines: string[] = [];
              for (const line of lines) {
                if (line.startsWith('event:')) {
                  eventName = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                  dataLines.push(line.slice(5).trim());
                }
              }
              const raw = dataLines.join('\n');
              let parsed: any = null;
              try {
                parsed = raw ? JSON.parse(raw) : null;
              } catch {
                parsed = null;
              }
              if (eventName === 'error') {
                throw new Error((parsed && parsed.message) ? parsed.message : 'chat_stream_failed');
              }
              if (eventName === 'acknowledgement' && parsed?.message) {
                setStreamAcknowledgement(String(parsed.message));
              }
              if (eventName === 'progress' && parsed?.message) {
                setStreamAcknowledgement(String(parsed.message));
              }
              if (eventName === 'answer' && parsed) {
                answerPayload = parsed;
              }
              splitIdx = buffer.indexOf('\n\n');
            }
          }
          return answerPayload;
          } finally {
            clearAll();   // release idle + total deadlines whether we finished, threw, or aborted
          }
        };

        let data: any = null;
        const hasChatImages = Array.isArray(chatPayload.images) && chatPayload.images.length > 0;
        if (!hasChatImages) {
          try {
            data = await tryStreamChat();
          } catch {
            data = null;
          }
        }
        if (!data) {
          // the fallback needs its own deadline too (review-6 #11) + the SAME idempotency key so
          // the backend can dedupe a stream-then-fallback double submit.
          const qctl = new AbortController();
          const qTimer = setTimeout(() => qctl.abort(), _SSE_TOTAL_MS);
          let r: Response;
          try {
            r = await fetch(apiUrl('/api/v1/chat/query'), {
              method: 'POST',
              credentials: 'include',
              headers: apiHeaders,
              body: JSON.stringify(chatPayload),
              signal: qctl.signal,
            });
          } finally {
            clearTimeout(qTimer);
          }
          data = await safeJson(r);
          // Replay protection (409): a duplicate of the previous turn was held back. Show a calm retry
          // hint instead of the generic "Backend unavailable" panel (the detail is an object, not a string).
          const replayDetail = data && (data.detail?.message ?? data.detail);
          if (r.status === 409 && replayDetail === 'chat_replay_detected') {
            const waitS = Number(data?.detail?.retry_after_seconds) || 5;
            setMessages(prev => [...prev, {
              role: 'assistant',
              content: `That looked like a duplicate of your previous message, so I held off to avoid sending it twice. Please try again in about ${waitS}s.`,
              timestamp: new Date(),
            }]);
            return;
          }
          if (!r.ok || !data) {
            const detailStr = (data && typeof data.detail === 'string') ? data.detail
              : (data && data.detail?.message) ? data.detail.message : `chat_query_failed (${r.status})`;
            throw new Error(detailStr);
          }
        }
        // A research-heavy turn may outlive the stream's synchronous wait while the
        // backend single-flight continues safely under the same idempotency key. Poll
        // that exact key for its cached completion; never resubmit with a new key.
        if (data?.status === 'in_progress') {
          const completionDeadline = Date.now() + 60_000;
          while (data?.status === 'in_progress' && Date.now() < completionDeadline) {
            await new Promise(resolve => setTimeout(resolve, 500));
            const qctl = new AbortController();
            const qTimer = setTimeout(() => qctl.abort(), 10_000);
            let completionResponse: Response;
            try {
              completionResponse = await fetch(apiUrl('/api/v1/chat/query'), {
                method: 'POST',
                credentials: 'include',
                headers: apiHeaders,
                body: JSON.stringify(chatPayload),
                signal: qctl.signal,
              });
            } finally {
              clearTimeout(qTimer);
            }
            const completion = await safeJson(completionResponse);
            if (!completionResponse.ok || !completion) {
              throw new Error(`chat_completion_poll_failed (${completionResponse.status})`);
            }
            data = completion;
          }
          if (data?.status === 'in_progress') {
            throw new Error('chat_completion_poll_timeout');
          }
        }
        mergeTrustEvidence(data);
        const governedOutcome = nonRecommendationOutcome(data);
        if (governedOutcome) {
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: governedOutcome.message,
            timestamp: new Date(),
          }]);
          setTraceId(normalizeTraceId(data.decision_trace_id || data.trace_id || null));
          // Intentionally preserve products, cart, right-panel mode, sourcing
          // intent, and the current fulfillment case. A refusal has no
          // commercial authority and must not look like a fresh empty search.
          return;
        }
        // Cart mutations may also preserve the current product/procurement panel, but they
        // still have to reach the cart lane below so its confirmation authority is rendered.
        // This guard is only for genuinely read-only case/status responses.
        if (data?.preserve_current_view === true && !(data as any)?.cart_mutation) {
          const operational = data?.constraints_used?.operational_constraints;
          if (operational && typeof operational === 'object') {
            setProcurementRequirements(current => ({ ...current, ...operational }));
            setSourcingIntent(current => current ? {
              ...current,
              requirements: { ...(current.requirements || {}), ...operational },
            } : current);
          }
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: String(data.assistant_message || 'The current case is unchanged.'),
            timestamp: new Date(),
          }]);
          setTraceId(normalizeTraceId(data.decision_trace_id || data.trace_id || null));
          return;
        }
        // ── V2 CART LANE (C2): the backend resolved this turn as a CART MUTATION ──
        // Covers both transports (chat_stream forwards chat_query's result verbatim). Three
        // shapes: applied → refresh the cart panel (the stale-panel bug) + server-undo chip on
        // destructive ops; needs_confirmation → render the confirm card (NOTHING has touched the
        // cart; Confirm applies via POST /cart/mutations/{plan_id}/apply, idempotent + stale-
        // guarded); needs_clarification → the ask IS the answer. Product machinery is skipped.
        if (data && (data as any).cart_mutation) {
          const cm = (data as any).cart_mutation;
          const multiIntentCandidate =
            data.multi_intent
            && Array.isArray((data.multi_intent as any).plan)
            && (data.multi_intent as any).plan.length > 0
              ? (data.multi_intent as MultiIntentPlan)
              : null;
          // A pure amendment has one authority: the durable cart-mutation
          // proposal. Treating its prior-line projection as a second
          // "multi-intent" surface hid the canonical Confirm button and made
          // buyers reselect the product. Keep MultiIntentCard only when this
          // turn genuinely introduces a new scoped product/category line.
          const nextMultiIntent = multiIntentCandidate?.plan.some((line) => line.scope === 'new')
            ? multiIntentCandidate
            : null;
          const cartConfirmedSlots = data.confirmed_slots && typeof data.confirmed_slots === 'object'
            ? data.confirmed_slots
            : null;
          const destructive = Array.isArray(cm.applied) && cm.applied.some((a: any) =>
            ['clear_all', 'keep_only', 'remove_items', 'clear_previous'].includes(String(a.action)));
          const supersededPlanIds = new Set(
            Array.isArray(cm.superseded_plan_ids)
              ? cm.superseded_plan_ids.map((value: any) => String(value))
              : [],
          );
          const nextMessage: ChatMessage = {
            role: 'assistant',
            content: String(data.assistant_message || 'Cart update processed.'),
            timestamp: new Date(),
            ...(cm.needs_confirmation && cm.plan_id && !nextMultiIntent
              ? { cartConfirm: { planId: String(cm.plan_id), ops: Array.isArray(cm.ops) ? cm.ops : [], expiresAt: cm.expires_at } }
              : {}),
            ...(data.cart_updated && destructive ? { undoServer: true } : {}),
          };
          setMessages(prev => [
            ...prev.map((message) => (
              message.cartConfirm && supersededPlanIds.has(message.cartConfirm.planId)
                ? {
                    ...message,
                    cartConfirm: undefined,
                    cartPlanStatus: `Superseded by newer plan ${String(cm.plan_id)}; it can no longer be applied.`,
                  }
                : message
            )),
            nextMessage,
          ]);
          setTraceId(normalizeTraceId(data.decision_trace_id || data.trace_id || null));
          setMultiIntent(nextMultiIntent);
          if (cartConfirmedSlots && Object.keys(cartConfirmedSlots).length > 0) {
            setConfirmedSlots(prev => ({ ...prev, ...cartConfirmedSlots }));
          }
          if (data.explanation && typeof data.explanation === 'object') {
            const explanation = data.explanation as ProductWhyExplanation;
            const explanationSku = String((data.explanation as any).sku || '').trim();
            if (explanationSku) setWhyDrawerSku(explanationSku);
            setWhyDrawerData(explanation);
            setWhyDrawerError(null);
            setWhyDrawerLoading(false);
          }
          if (data.delivery_feasibility && typeof data.delivery_feasibility === 'object') {
            setProcurementRequirements(current => ({
              ...current,
              delivery_feasibility: data.delivery_feasibility,
            }));
          }
          if (data.cart_updated) {
            // Quantity-specific alternatives came from the recommendation turn before this
            // mutation. Keeping them would show the old requested quantity above the new cart.
            setBulkAlternatives([]);
            await refreshCart();
            switchRightPanelMode('cart');
          }
          if (nextMultiIntent) switchRightPanelMode('cart');
          return;
        }

        const prods = (data.products || []) as Product[];
        const shelf = data.shelf && Array.isArray(data.shelf.bands)
          ? data.shelf as RecommendationShelfContract
          : null;
        setRecommendationShelf(shelf);
        const shelfProducts = (shelf?.bands || []).flatMap((band) => Array.isArray(band.cards) ? band.cards : []);
        const allVisibleProducts = Array.from(
          new Map([...prods, ...shelfProducts].map((product) => [String(product.sku), product])).values(),
        );
        if (imageRecommendationTurn) {
          setCanonicalImageProducts(prods.slice(0, 10));
          setCanonicalImageSummary(String(data.assistant_message || data.summary || ''));
        }
        // bulk-order carry-through: remember the conversation's requested unit count for the Add buttons
        {
          const _rq = Number((data as any).requested_quantity);
          setPendingBulkQty(Number.isFinite(_rq) && _rq > 1 ? Math.min(1000, Math.floor(_rq)) : null);
          setPendingBulkBudget(normalizePendingBulkBudget(
            (data as any).bulk_budget,
            (data as any).confirmed_slots,
          ));
        }
        setExternalResearch(Array.isArray(data.external_research) ? (data.external_research as ExternalResearchItem[]) : []);
        setFulfilmentCase(data.fulfillment_case && (data.fulfillment_case as any).case_id ? (data.fulfillment_case as FulfilmentCaseSummary) : null);
        // FLUID-procurement preview (FULFILLMENT_DEFER_TO_CART): a buyer-safe sourcing split with no durable
        // case — the buyer confirms it (GATE 1) via SourcingIntentCard to materialize the cases.
        setSourcingIntent((current) => {
          if (data.sourcing_intent && Array.isArray((data.sourcing_intent as any).lines)) {
            return data.sourcing_intent as SourcingIntent;
          }
          const operational = data?.constraints_used?.operational_constraints;
          if (current && operational && typeof operational === 'object') {
            // A delivery/payment amendment may intentionally produce no new
            // product slate. Preserve the selected sourcing lines and attach
            // only the backend-clamped operational facts to the eventual
            // buyer-commitment boundary.
            return {
              ...current,
              requirements: { ...(current.requirements || {}), ...operational },
            };
          }
          return current;
        });
        if (data?.sourcing_intent?.requirements && typeof data.sourcing_intent.requirements === 'object') {
          setProcurementRequirements(current => ({
            ...current,
            ...data.sourcing_intent.requirements,
          }));
        }
        // P0 multi-intent: present only on a genuine mixed turn (amend + scoped new lines). Surface it so
        // the buyer confirms the qty change and adds the scoped picks — never silently applied.
        const nextMultiIntent =
          data.multi_intent
          && Array.isArray((data.multi_intent as any).plan)
          && (data.multi_intent as any).plan.length > 0
            ? (data.multi_intent as MultiIntentPlan)
            : null;
        setMultiIntent(nextMultiIntent);
        // A mixed-intent response can intentionally contain no recommendation
        // products: its actionable output is the governed confirmation plan.
        // Open the cart/procurement panel explicitly so that plan is visible.
        if (nextMultiIntent) switchRightPanelMode('cart');
        setBulkAlternatives(Array.isArray(data.fulfillment_options) ? (data.fulfillment_options as BulkAlternativeOption[]) : []);
        const respAssistant = data.assistant_message || '';
        // Async-narration handoff: recommend returned the deterministic answer now + a job id for the
        // richer LLM prose. We tag the assistant message and poll it in to replace the text in place.
        const narrationJobId = (typeof data.llm_summary_job_id === 'string' && data.llm_summary_job_id)
          ? data.llm_summary_job_id : null;
        const nextQuestions = Array.isArray(data.next_questions) ? data.next_questions : [];
        const normalizedNextQuestions = normalizeNextQuestions(nextQuestions);
        const isDisambiguation = data.disambiguation === true;
        const disambiguationOpts = Array.isArray(data.next_questions) ? data.next_questions.map((nq: any) => typeof nq === 'string' ? nq : nq?.text || '') : [];
        const complexity = data.complexity || null;
        const backendApplied = data.nqe_selection_applied || null;
        const buyerRequirementClaims = Array.isArray(data.buyer_requirement_claims)
          ? data.buyer_requirement_claims as BuyerRequirementClaim[]
          : [];
        const buyerRequirementProposal = data.buyer_requirement_proposal
          && typeof data.buyer_requirement_proposal === 'object'
          && data.buyer_requirement_proposal.proposal_id
          ? data.buyer_requirement_proposal as ChatMessage['buyerRequirementProposal']
          : undefined;
        const backendConfirmedSlots = data.confirmed_slots && typeof data.confirmed_slots === 'object'
          ? data.confirmed_slots
          : null;
        const agentStepsReadable: string[] | undefined = (() => {
          const steps = data?.proposal?.agent_steps_readable || data?.agent_steps_readable;
          return Array.isArray(steps) && steps.length > 0 ? steps : undefined;
        })();
        const budgetViability = (data.budget_viability && typeof data.budget_viability === 'object') ? data.budget_viability : null;
        const budgetAdvice = (budgetViability?.status === 'low' && typeof budgetViability?.advice === 'string') ? budgetViability.advice.trim() : null;
        const panelContract = (data.right_panel && typeof data.right_panel === 'object') ? data.right_panel as RightPanelContract : null;
        setRightPanelContract(panelContract);
        if (buyerRequirementClaims.length > 0) {
          // An upload is a pending evidence proposal, not permission to keep presenting
          // an earlier case's shelves as if they reflect the newly extracted claims.
          setProductShelves(null);
        }
        if (data?.ambiguity_exploration?.schema_version === 'ambiguity-exploration-v1') {
          const incomingCaseId = String(data.ambiguity_exploration.case_id || '');
          const continuesActiveCase = Boolean(
            activeShoppingCase?.case_id && activeShoppingCase.case_id === incomingCaseId,
          );
          // The normal chat response can carry the original provisional projection.
          // It must not downgrade a researched same-case projection or replace the
          // durable case trace after later quantity/budget follow-ups.
          if (!continuesActiveCase) {
            setAmbiguityExploration(data.ambiguity_exploration as AmbiguityExploration);
          }
          setActiveShoppingCase({
            case_id: incomingCaseId,
            retained_purpose: String(data.ambiguity_exploration.retained_purpose || ''),
          });
          if (!continuesActiveCase && data?.product_shelves?.schema_version === 'product-shelves-v1') {
            setProductShelves(data.product_shelves as ProductShelfProjection);
          }
          switchRightPanelMode('grid');
        }
        if (
          data?.shopping_case_id
          && data?.shopping_case_retained_purpose
          && !activeShoppingCase?.case_id
        ) {
          setActiveShoppingCase({
            case_id: String(data.shopping_case_id),
            retained_purpose: String(data.shopping_case_retained_purpose),
          });
        }
        setTraceEvidence(data.evidence || null);
        const nextTraceId = normalizeTraceId(data.decision_trace_id || data.trace_id || data.decision_id || data.case_id || null);
        // Pin the sourcing trace to THIS turn when it produced a sourcing preview. If the turn carries NO
        // procurement context at all (no sourcing preview, no open case, no bulk options/quantity), RELEASE
        // the sticky pin — otherwise a later single-unit query would still resolve the prior bulk turn's
        // Procurement tab and show its stale split. A turn that still carries procurement context (an open
        // case or bulk options) keeps the pin so an active plan isn't unlinked.
        const turnHasSourcingPreview = Boolean(
          data.sourcing_intent && Array.isArray((data.sourcing_intent as any).lines) && (data.sourcing_intent as any).lines.length > 0);
        const turnHasFulfillmentOptions = Array.isArray(data.fulfillment_options)
          && data.fulfillment_options.length > 0;
        const turnHasProcurementContext = turnHasSourcingPreview
          || Boolean(data.fulfillment_case && (data.fulfillment_case as any).case_id)
          || turnHasFulfillmentOptions
          || (Number((data as any).requested_quantity) > 1);
        setSourcingTraceId((current) => nextSourcingTraceId(
          current,
          nextTraceId,
          turnHasSourcingPreview,
          turnHasFulfillmentOptions,
          turnHasProcurementContext,
        ));
        persistOperatorMetrics(data.timing_breakdown, nextTraceId, Array.isArray(chatPayload.images) && chatPayload.images.length > 0 ? 'chat+image' : 'chat');
        try {
          const persona = String(data.buyer_persona || data.buyer_persona_candidate || '').trim();
          if (persona) localStorage.setItem('shopsquire_last_persona', persona);
          const useCase = String(
            (data.constraints_used && typeof data.constraints_used === 'object' ? (data.constraints_used as any).use_case : '') ||
            data.detected_use_case ||
            ''
          ).trim();
          if (useCase) localStorage.setItem('shopsquire_last_use_case', useCase);
        } catch {}
        if (backendConfirmedSlots && Object.keys(backendConfirmedSlots).length > 0) {
          setConfirmedSlots(prev => ({ ...prev, ...backendConfirmedSlots }));
        }
        // Update NQE history with backend-confirmed applied constraints
        if (backendApplied && Object.keys(backendApplied).length > 0 && nqeHistory.length > 0) {
          setNqeHistory(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && !last.appliedConstraints) {
              updated[updated.length - 1] = { ...last, appliedConstraints: backendApplied };
            }
            return updated;
          });
        }
        // A shopping case is the durable multi-turn audit identity. Individual
        // chat turns still retain their own trace IDs server-side, but replacing
        // the visible trace with the latest turn made approved research appear
        // to vanish after a quantity or deadline follow-up.
        setTraceId(normalizeTraceId(ambiguityExploration?.trace_id || nextTraceId));

        // Auto-open decision trace when image is security-flagged so the analyst sees the full matrix immediately
        if (
          nextTraceId &&
          (data.status === 'image_flagged_vision_results' || data.status === 'image_flagged_text_results') &&
          data.security_alert
        ) {
          setTraceOpen(true);
        }

        if (isDisambiguation) {
          // Show disambiguation buttons instead of products
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: respAssistant || 'I see you uploaded an image. What would you like to do?',
            timestamp: new Date(),
            disambiguation: true,
            disambiguationOptions: disambiguationOpts,
            complexity,
            ...(backendApplied && Object.keys(backendApplied).length > 0 ? { nqeSelectionApplied: backendApplied } : {}),
            ...(agentStepsReadable ? { agentStepsReadable } : {}),
            ...(data.evidence ? { evidence: data.evidence } : {}),
            ...(buyerRequirementClaims.length > 0 ? { buyerRequirementClaims } : {}),
            ...(buyerRequirementProposal ? { buyerRequirementProposal } : {}),
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else if (prods.length > 0) {
          const visibleProducts = allVisibleProducts.slice(0, 12);
          setDisplayProducts(visibleProducts);
          if (panelContract?.mode === 'support') switchRightPanelMode('faq');
          else if (cartUpsellIntent) switchRightPanelMode('cart');
          else if (hasImages && !complaintIntent && !explicitComplaintIntent) switchRightPanelMode('visual_search');
          else switchRightPanelMode(mode === 'none' ? 'grid' : mode);
          const whySummary = _stripTechnicalTokens(summarizeWhy(prods));
          const hasAssistantBody = typeof respAssistant === 'string' && respAssistant.trim().length > 0;
          const baseLine = hasAssistantBody
            ? _stripTechnicalTokens(respAssistant.trim())
            : `I found ${prods.length} ${mode === 'compare' ? 'products to compare' : 'matching products'} and I'm showing the top ${visibleProducts.length}.`;
          const includeWhy = whySummary && !/top picks:/i.test(baseLine);
          const budgetNote = budgetAdvice && !baseLine.includes('budget') ? `\n\n⚠️ Budget note: ${budgetAdvice}` : '';

          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: `${baseLine}${includeWhy ? `\n\n${whySummary}` : ''}${budgetNote}`,
            timestamp: new Date(),
            complexity,
            nextQuestions: normalizedNextQuestions,
            ...(backendApplied && Object.keys(backendApplied).length > 0 ? { nqeSelectionApplied: backendApplied } : {}),
            ...(agentStepsReadable ? { agentStepsReadable } : {}),
            ...(data.evidence ? { evidence: data.evidence } : {}),
            ...(buyerRequirementClaims.length > 0 ? { buyerRequirementClaims } : {}),
            ...(buyerRequirementProposal ? { buyerRequirementProposal } : {}),
            ...(narrationJobId ? { narrationJobId } : {}),
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else {
          const slateDisposition = String((data as any).slate_disposition || 'retain');
          if (slateDisposition === 'clear') {
            setDisplayProducts([]);
            setRecommendationShelf(null);
            if (['grid', 'list', 'visual_search'].includes(rightPanelMode)) {
              switchRightPanelMode('none');
            }
          }
          // A material clarification may retain the prior slate as context. An authoritative
          // zero-result response clears it above so old products cannot appear to satisfy new
          // constraints.
          if (panelContract?.mode === 'support') switchRightPanelMode('faq');
          else if (cartUpsellIntent) switchRightPanelMode('cart');
          // else: keep current panel mode unchanged
          const nqePrompt = nextQuestions.some((item: any) => {
            const questionText = String(item?.text || item?.question || '').trim();
            return Boolean(questionText) && String(respAssistant || '').includes(questionText);
          }) ? '' : formatNextQuestions(nextQuestions);
          const noProdsBase = respAssistant || 'I could not find products matching that query.';
          const budgetNote = budgetAdvice ? `\n\n⚠️ Budget note: ${budgetAdvice}` : '';
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: noProdsBase + nqePrompt + budgetNote,
            timestamp: new Date(),
            complexity,
            nextQuestions: normalizedNextQuestions,
            ...(backendApplied && Object.keys(backendApplied).length > 0 ? { nqeSelectionApplied: backendApplied } : {}),
            ...(agentStepsReadable ? { agentStepsReadable } : {}),
            ...(data.evidence ? { evidence: data.evidence } : {}),
            ...(buyerRequirementClaims.length > 0 ? { buyerRequirementClaims } : {}),
            ...(buyerRequirementProposal ? { buyerRequirementProposal } : {}),
            ...(narrationJobId ? { narrationJobId } : {}),
          };
          setMessages(prev => [...prev, assistantMsg]);
        }
        // Async narration: poll the richer LLM prose and replace the tagged message in place. Best-effort
        // — on timeout/error we keep the deterministic grounded answer already shown.
        if (narrationJobId) {
          const _poll = (() => {
            activeNarrationJobs.add(narrationJobId);
            let tries = 0;
            // Exponential backoff 1250 → 2500 → 5000ms (capped): ~12 ticks keeps roughly the
            // old ~45s budget (matches model-descriptor narration timeouts) with a third of
            // the fetches. Sibling jobs from earlier messages stay live — only this job's
            // removal from activeNarrationJobs stops this chain.
            const maxTries = 12;
            const nextDelayMs = () => Math.min(1250 * Math.pow(2, tries), 5000);
            const tick = async () => {
              // Cancelled (message content replaced / job cleared): stop the chain, no fetch.
              if (!activeNarrationJobs.has(narrationJobId)) {
                activeNarrationJobs.delete(narrationJobId);
                return;
              }
              tries += 1;
              try {
                const nr = await fetch(apiUrl(`/api/v1/recommend/narration/${encodeURIComponent(narrationJobId)}`), {
                  credentials: 'include', headers: apiHeaders,
                });
                const nd = await safeJson(nr);
                const status = nd && nd.status;
                const prose = (nd && typeof nd.assistant_message === 'string') ? nd.assistant_message.trim() : '';
                if (status === 'done' && prose) {
                  const polished = _stripTechnicalTokens(prose);
                  // The mapper below clears narrationJobId from the message, so drop the job
                  // from the registry with it — the id is dead once the content is swapped in.
                  setMessages(prev => prev.map(m =>
                    m.narrationJobId === narrationJobId
                      ? { ...m, content: polished, narrationJobId: undefined }
                      : m));
                  activeNarrationJobs.delete(narrationJobId);
                  return;
                }
                // done-with-no-prose = claim guard rejected the LLM draft: the deterministic
                // grounded answer already shown IS the final answer — stop polling now.
                if (status === 'done' || status === 'error' || tries >= maxTries) {
                  activeNarrationJobs.delete(narrationJobId);
                  return;
                }
              } catch {
                if (tries >= maxTries) {
                  activeNarrationJobs.delete(narrationJobId);
                  return;
                }
              }
              setTimeout(tick, nextDelayMs());
            };
            setTimeout(tick, nextDelayMs());
          });
          _poll();
        }
      }
    } catch (e: any) {
      setTraceId(null);
      switchRightPanelMode('none');
      setRightPanelContract(null);
      const errMsg = (e && (e.message || String(e))) ? (e.message || String(e)) : 'unknown_error';
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Backend unavailable. Decision Trace was not recorded.\n\nTroubleshooting:\n- Confirm FastAPI is running (default: http://127.0.0.1:8080).\n- Vite proxy should forward /api to the backend.\n- Error: ${errMsg}`,
        timestamp: new Date(),
      }]);
      return;
    } finally {
      setStreamAcknowledgement(null);
      setIsThinking(false);
    }
  };

  const handleQuickAction = (query: string) => {
    setInputValue(query);
    setTimeout(() => handleSend({ queryOverride: query }), 100);
  };

  const acceptBuyerRequirementProposal = useCallback(async (
    message: ChatMessage,
    acceptedClaimIds: string[],
    researchChoice: 'local_only' | 'research_and_corroborate',
    corrections: Record<string, unknown>[] = [],
  ) => {
    const proposal = message.buyerRequirementProposal;
    if (!proposal) throw new Error('This requirement proposal is missing its case identity.');
    const allIds = (message.buyerRequirementClaims || []).map((claim) => claim.claim_id);
    const response = await fetch(apiUrl(
      `/api/v1/shopping-cases/${encodeURIComponent(proposal.case_id)}`
      + `/requirement-proposals/${encodeURIComponent(proposal.proposal_id)}/accept`,
    ), {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': `accept-${proposal.proposal_id}-${proposal.proposal_version}`,
        'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
        ...csrfHeaders(),
      },
      body: JSON.stringify({
        uid,
        expected_proposal_version: proposal.proposal_version,
        accepted_claim_ids: acceptedClaimIds,
        rejected_claim_ids: allIds.filter((claimId) => !acceptedClaimIds.includes(claimId)),
        corrections,
        research_choice: researchChoice,
      }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(String(payload?.detail?.code || payload?.detail || 'Requirement acceptance failed.'));
    }
    if (payload?.product_shelves?.schema_version === 'product-shelves-v1') {
      setProductShelves(payload.product_shelves as ProductShelfProjection);
      switchRightPanelMode('grid');
    }
    if (payload?.corroboration?.ambiguity_exploration?.schema_version === 'ambiguity-exploration-v1') {
      setAmbiguityExploration(payload.corroboration.ambiguity_exploration as AmbiguityExploration);
    }
    setTraceId(normalizeTraceId(payload?.trace_id || traceId));
    setMessages((current) => [...current, {
      role: 'assistant',
      content: researchChoice === 'research_and_corroborate'
        ? payload?.corroboration?.status === 'blocked'
          ? `I accepted those as provisional constraints, but corroboration is blocked: ${payload.corroboration.message || payload.corroboration.reason}. Product fit remains provisional.`
          : payload?.corroboration?.evidence_outcome === 'context_only'
            ? 'I accepted those as provisional constraints and completed approved-source research in the same case. It found authoritative context but no matching product requirements, so these constraints and product fit remain provisional.'
            : 'I accepted those as provisional constraints and completed approved-source corroboration in the same case. Remaining unknowns stay conditional.'
        : 'I accepted those as provisional constraints and reranked the local catalog without calling an external provider.',
      timestamp: new Date(),
      buyerClaimReconciliation: Array.isArray(payload?.buyer_claim_reconciliation)
        ? payload.buyer_claim_reconciliation as BuyerClaimReconciliation[] : undefined,
    }]);
  }, [uid, traceId, switchRightPanelMode]);

  const researchAmbiguousShoppingCase = useCallback(async () => {
    if (!ambiguityExploration?.case_id) {
      throw new Error('This exploration is missing its shopping-case identity.');
    }
    if (!ambiguityExploration.research_plan_id) {
      throw new Error('This case has no governed research plan. Upload requirements or continue provisionally.');
    }
    setIsThinking(true);
    try {
      const response = await fetch(apiUrl(
        `/api/v1/shopping-cases/${encodeURIComponent(ambiguityExploration.case_id)}/research`,
      ), {
        method: 'POST', credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
          ...csrfHeaders(),
        },
        body: JSON.stringify({
          uid,
          research_plan_id: ambiguityExploration.research_plan_id,
          ambiguity_object_ids: (ambiguityExploration.ambiguity_objects || []).map((item) => item.ambiguity_id),
          hypothesis_ids: (ambiguityExploration.interpretations || [])
            .map((item) => item.hypothesis_id)
            .filter((value): value is string => Boolean(value)),
          research_authorized: true,
          refresh_authorized: false,
        }),
      });
      const payload = await safeJson(response);
      if (!response.ok) {
        throw new Error(String(payload?.detail?.message || payload?.detail?.code || payload?.detail || 'Approved-source research failed.'));
      }
      if (payload?.product_shelves?.schema_version === 'product-shelves-v1') {
        setProductShelves(payload.product_shelves as ProductShelfProjection);
      }
      if (payload?.ambiguity_exploration?.schema_version === 'ambiguity-exploration-v1') {
        setAmbiguityExploration(payload.ambiguity_exploration as AmbiguityExploration);
      }
      setTraceId(normalizeTraceId(payload?.trace_id || ambiguityExploration.trace_id || traceId));
      setMessages((current) => [...current, {
        role: 'assistant',
        content: payload?.evidence_outcome === 'context_only'
          ? `Approved-source research completed in the same shopping case. It established ${payload?.research?.context_claims?.length || 0} context claims but no authoritative product requirements, so the shortlist remains provisional. Tell me the named software/version or accept uploaded requirements to continue. No cart or supplier action was authorized.`
          : `Approved-source research completed in the same shopping case. I compiled ${payload?.research?.claims?.length || 0} scoped product claims and kept ${payload?.research?.unresolved?.length || 0} source or capability gaps visible. No cart or supplier action was authorized.`,
        timestamp: new Date(),
      }]);
    } catch (error: any) {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: `Approved-source research could not complete: ${error?.message || String(error)} You can upload requirements or continue provisionally.`,
        timestamp: new Date(),
      }]);
    } finally {
      setIsThinking(false);
    }
  }, [ambiguityExploration, uid, traceId]);

  const resolveBuyerEvidenceSource = useCallback(async (
    hint: { source_url?: string; vendor_name?: string },
    researchAuthorized: boolean,
  ) => {
    if (!ambiguityExploration?.case_id) {
      throw new Error('This exploration is missing its shopping-case identity.');
    }
    const response = await fetch(apiUrl(
      `/api/v1/shopping-cases/${encodeURIComponent(ambiguityExploration.case_id)}/evidence-source-resolutions`,
    ), {
      method: 'POST', credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
        ...csrfHeaders(),
      },
      body: JSON.stringify({ uid, ...hint, research_authorized: researchAuthorized }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      throw new Error(String(payload?.detail?.message || payload?.detail?.code || payload?.detail || 'Evidence-source resolution failed.'));
    }
    if (researchAuthorized && payload?.research_status === 'completed') {
      if (payload?.product_shelves?.schema_version === 'product-shelves-v1') {
        setProductShelves({
          ...payload.product_shelves,
          evidence_status: payload?.evidence_outcome === 'product_requirements'
            ? 'researched' : payload?.evidence_outcome === 'context_only' ? 'context_only' : 'unresolved',
          official_claim_count: Array.isArray(payload?.research?.claims) ? payload.research.claims.length : 0,
          context_claim_count: Array.isArray(payload?.research?.context_claims) ? payload.research.context_claims.length : 0,
        } as ProductShelfProjection);
      }
      setAmbiguityExploration((current) => current ? {
        ...current,
        status: payload?.evidence_outcome === 'product_requirements'
          ? 'researched' : payload?.evidence_outcome === 'context_only' ? 'context_only' : 'unresolved',
        execution: 'buyer_authorized_canonical_fetch_completed',
        evidence: payload?.evidence_outcome || 'unresolved',
        provider_accounting: payload?.provider_accounting || current.provider_accounting,
      } : current);
      setTraceId(normalizeTraceId(payload?.trace_id || traceId));
      setMessages((current) => [...current, {
        role: 'assistant',
        content: payload?.evidence_outcome === 'product_requirements'
          ? 'I fetched the reviewed canonical publisher page you selected, compiled scoped requirements, and reranked this same case. Unknowns remain visible; no cart or supplier action was authorized.'
          : 'I fetched the reviewed canonical publisher page, but it did not establish product requirements for this case. The shortlist remains provisional and no cart or supplier action was authorized.',
        timestamp: new Date(),
      }]);
    }
    return payload?.resolution || { status: 'unresolved', reason: 'resolution_not_recorded' };
  }, [ambiguityExploration, uid, traceId]);

  const proposeResearchedProduct = useCallback(async (item: ShelfProduct, quantity: number) => {
    if (!ambiguityExploration?.case_id) return;
    const freshQuantities = (item.availability || [])
      .filter((row) => row.freshness_status === 'fresh' && row.quantity != null && ['in_stock', 'available'].includes(row.status))
      .map((row) => Number(row.quantity || 0));
    const availabilityKnown = freshQuantities.length > 0 || (item.availability || []).some(
      (row) => row.freshness_status === 'fresh' && (row.quantity === 0 || ['sold_out', 'built_to_order', 'at_supplier'].includes(row.status)),
    );
    const availableNow = availabilityKnown ? freshQuantities.reduce((sum, value) => sum + value, 0) : null;
    if (availableNow == null || quantity > availableNow) {
      const alternatives = productShelves?.shelves.flatMap((shelf) => [...shelf.initial, ...shelf.next_page]) || [];
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
    const response = await fetch(apiUrl(
      `/api/v1/shopping-cases/${encodeURIComponent(ambiguityExploration.case_id)}/cart-proposals`,
    ), {
      method: 'POST', credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
        ...csrfHeaders(),
      },
      body: JSON.stringify({ uid, sku, quantity }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      setMessages((current) => [...current, {
        role: 'assistant',
        content: String(payload?.detail?.message || payload?.detail?.code || payload?.detail || 'Cart proposal failed.'),
        timestamp: new Date(),
      }]);
      return;
    }
    setMessages((current) => [...current, {
      role: 'assistant',
      content: `I prepared a case-bound change for ${quantity} × ${sku}. Nothing has changed yet; confirm the plan below. Numeric availability is not attested, so any shortfall remains supplier-sourced.`,
      timestamp: new Date(),
      cartConfirm: {
        planId: payload.plan_id,
        ops: payload.ops,
        expiresAt: payload.expires_at,
      },
    }]);
  }, [ambiguityExploration, productShelves, uid]);

  const assessSupplierContinuation = useCallback(async (deadlineDays: number) => {
    if (!supplierContinuation) return;
    const response = await fetch(apiUrl(
      `/api/v1/shopping-cases/${encodeURIComponent(supplierContinuation.caseId)}/fulfillment-options`,
    ), {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''), ...csrfHeaders() },
      body: JSON.stringify({
        uid, requested_quantity: supplierContinuation.requestedQuantity,
        available_now: supplierContinuation.availableNow ?? 0,
        known_lead_time_days: 8, deadline_days: deadlineDays,
        has_next_best: Boolean(supplierContinuation.substituteSku),
        has_architecture_alternative: true,
      }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      setSupplierContinuation((current) => current ? { ...current, error: apiErrorMessage(payload, 'Fulfilment assessment failed.') } : current);
      return;
    }
    setSupplierContinuation((current) => current ? {
      ...current, deadlineDays, choices: payload?.choices || [], error: undefined,
    } : current);
  }, [supplierContinuation, uid]);

  const selectSupplierContinuation = useCallback(async (choiceId: string) => {
    if (!supplierContinuation) return;
    if (choiceId === 'alternative_architecture') {
      setMessages((current) => [...current, { role: 'assistant', content: 'I kept the preferred laptop visible and expanded the architecture-specific shelves. Compare fixed workstation, mobile workstation and hosted alternatives before selecting a commercial path.', timestamp: new Date() }]);
      return;
    }
    if (choiceId === 'relax_constraint') {
      setMessages((current) => [...current, { role: 'assistant', content: 'Tell me which degree of freedom to change: quantity, delivery date, budget or a workload requirement. Nothing has changed yet.', timestamp: new Date() }]);
      return;
    }
    const choice = choiceId === 'next_best_now' ? 'next_best_now' : choiceId;
    setSupplierContinuation((current) => current ? { ...current, status: 'selecting' } : current);
    const response = await fetch(apiUrl(
      `/api/v1/shopping-cases/${encodeURIComponent(supplierContinuation.caseId)}/fulfillment-selections`,
    ), {
      method: 'POST', credentials: 'include',
      headers: {
        'Content-Type': 'application/json', 'Idempotency-Key': supplierContinuation.selectionKey,
        'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''), ...csrfHeaders(),
      },
      body: JSON.stringify({
        uid, expected_revision: supplierContinuation.revision ?? 0, choice,
        preferred_sku: supplierContinuation.preferredSku,
        substitute_sku: supplierContinuation.substituteSku,
        requested_quantity: supplierContinuation.requestedQuantity,
        available_now: supplierContinuation.availableNow ?? 0,
        deadline_days: supplierContinuation.deadlineDays,
      }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      setSupplierContinuation((current) => current ? { ...current, status: 'review', error: apiErrorMessage(payload, 'Supplier fixture failed.') } : current);
      return;
    }
    setSupplierContinuation((current) => current ? {
      ...current, selectedChoice: choice, selectionId: payload.selection_id,
      revision: payload.revision, offers: payload.offers || [], status: 'offers', error: undefined,
    } : current);
  }, [supplierContinuation, uid]);

  const confirmSupplierContinuation = useCallback(async () => {
    if (!supplierContinuation?.selectionId || supplierContinuation.revision == null) return;
    const offer = supplierContinuation.offers?.find((row) => row.offer_id === supplierContinuation.selectedOfferId);
    setSupplierContinuation((current) => current ? { ...current, status: 'confirming' } : current);
    const response = await fetch(apiUrl(
      `/api/v1/shopping-cases/${encodeURIComponent(supplierContinuation.caseId)}/fulfillment-selections/${encodeURIComponent(supplierContinuation.selectionId)}/confirm-cart`,
    ), {
      method: 'POST', credentials: 'include',
      headers: {
        'Content-Type': 'application/json', 'Idempotency-Key': supplierContinuation.confirmationKey,
        'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''), ...csrfHeaders(),
      },
      body: JSON.stringify({
        uid, expected_revision: supplierContinuation.revision,
        selected_offer_id: supplierContinuation.selectedOfferId || null,
        substitution_authorized: offer?.relationship === 'compatible_substitute',
      }),
    });
    const payload = await safeJson(response);
    if (!response.ok) {
      setSupplierContinuation((current) => current ? { ...current, status: 'offers', error: apiErrorMessage(payload, 'Cart confirmation failed.') } : current);
      return;
    }
    await refreshCart();
    setSupplierContinuation((current) => current ? { ...current, status: 'applied', error: undefined } : current);
    setMessages((current) => [...current, {
      role: 'assistant', content: `Applied the explicitly confirmed fulfilment selection: ${payload.confirmed_quantity} × ${payload.confirmed_sku}. No real supplier was contacted.`, timestamp: new Date(),
    }]);
  }, [supplierContinuation, uid]);

  /** Disambiguation button click → re-send with the chosen intent */
  const handleDisambiguationSelect = (option: string) => {
    setInputValue(option);
    setTimeout(() => handleSend({ queryOverride: option }), 100);
  };

  const handleNqeOptionSelect = (
    question: { id: string; text: string; goal?: string; options?: { id: string; label: string; value?: string }[] },
    option: { id: string; label: string; value?: string },
  ) => {
    const label = String(option?.label || '').trim();
    if (!label) return;
    // Record in NQE history for cross-turn context
    const interaction: NqeInteraction = {
      questionId: question.id,
      questionText: question.text,
      optionId: option.id,
      optionLabel: label,
      optionValue: option.value,
      ts: Date.now(),
    };
    setNqeHistory(prev => [...prev, interaction]);
    setInputValue(label);
    setTimeout(() => handleSend({
      queryOverride: label,
      nqeSelection: {
        question_id: question.id,
        option_id: option.id,
        option_label: label,
        option_value: option.value,
      },
    }), 100);
  };

  /** Drag-and-drop on chat body */
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files);
    handleAttach(files);
  }, [handleAttach]);

  /** Paste images in chat body */
  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = Array.from(e.clipboardData.items);
    const files: File[] = [];
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      handleAttach(files);
    }
  }, [handleAttach]);

  /** Auto-resize textarea */
  const handleTextareaInput = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }, []);

  const backgroundInertProps = chatOpen
    ? ({ inert: '', 'aria-hidden': true } as any)
    : {};

  return (
    <div className={styles.page}>
      {/* Homepage Header */}
      <header className={styles.header} {...backgroundInertProps}>
        <div className={styles.headerInner}>
          <div className={styles.logo}>Shop<span>Squire</span></div>
          <div className={styles.searchBox}>
            <input
              type="text"
              placeholder="Search products..."
              aria-label="Search the product catalogue"
              className={styles.searchInput}
              value={headerSearchValue}
              onChange={(e) => setHeaderSearchValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleHeaderSearch(); }}
            />
            <button className={styles.searchBtn} onClick={handleHeaderSearch}>Search</button>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.headerBtn} onClick={() => { refreshCart(); switchRightPanelMode('cart'); setChatOpen(true); }}>
              Cart ({(cart?.items || []).length || 0})
            </button>
            {authUser ? (
              <>
                <span style={{ fontSize: 13, color: '#555', marginRight: 4 }}>{authUser.name}</span>
                <button className={styles.headerBtn} onClick={() => {
                  clearStoredAuthIdentity();
                  clearStoredRole();
                  clearStoredUid();
                  setAuthUser(null);
                  fetch(apiUrl('/api/v1/auth/logout'), {
                    method: 'POST',
                    credentials: 'include',
                    headers: csrfHeaders(),
                  }).catch(() => {});
                }}>Logout</button>
                <button className={styles.headerBtn} onClick={() => setShowAdminDash(true)}>Dashboard</button>
              </>
            ) : (
              <button className={styles.headerBtn} onClick={() => setShowLogin(true)}>Login</button>
            )}
          </div>
        </div>
      </header>

      {/* Homepage Product Grid */}
      <main className={styles.main} {...backgroundInertProps}>
        <StorefrontTrustBanner
          localEnvironment={localEnvironment}
          catalogueState={catalogueState}
          evidence={trustEvidence}
        />
        <StorefrontEmphasisBanner />
        <div className={styles.categoryBar}>
          <h1 className={styles.categoryTitle}>Laptops</h1>
          <div className={styles.filters}>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('Show me the best value laptops sorted by price')}>Price</button>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('Show me laptops with 16GB RAM or more')}>RAM</button>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('What laptop brands do you carry?')}>Brand</button>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('Show me laptops with a dedicated GPU or RTX graphics card')}>GPU</button>
          </div>
        </div>
        {catalogueState === 'loading' && (
          <div className={styles.catalogueNotice} role="status">Loading catalogue…</div>
        )}
        {catalogueState === 'unavailable' && (
          <div className={styles.catalogueNotice} role="alert">
            The catalogue is unavailable. Product facts could not be loaded, so no catalogue recommendations are shown.
          </div>
        )}
        {catalogueState === 'empty' && (
          <div className={styles.catalogueNotice} role="status">
            The catalogue loaded successfully but contains no products.
          </div>
        )}
        {catalogueState === 'ready' && (
          <ProductGrid products={displayProducts.length > 0 ? filteredDisplayProducts : products} onAdd={addToCart} viewMode="grid" />
        )}
        {!chatOpen && fulfilmentCase && <FulfilmentOptions caseSummary={fulfilmentCase} uid={uid} pollMs={4000} />}
        <ExternalResearchPanel items={externalResearch} />
      </main>

      {/* Floating Chat Button */}
      {!chatOpen && (
        <button className={styles.chatFab} onClick={() => setChatOpen(true)}>
          <ChatIcon />
          <span className={styles.fabLabel}>Ask Me!</span>
        </button>
      )}

      {/* Chat Overlay */}
      {chatOpen && (
        <div className={styles.overlay}>
          <div className={`${styles.chatContainer} ${hasRightPanel ? styles.withPanel : ''}`}>
            {/* Chat Panel */}
            <div className={styles.chatPanel}>
              <div className={styles.chatHeader}>
                <div className={styles.chatHeaderLeft}>
                  <h2 className={styles.chatTitle}>ShopSquire Assistant</h2>
                  <span
                    className={`${styles.backendPill} ${backendStatus.ok ? styles.backendUp : styles.backendDown}`}
                    title={
                      backendStatus.checkedAt
                        ? `Backend: ${backendStatus.ok ? 'UP' : 'DOWN'}${backendStatus.latencyMs != null ? ` (${backendStatus.latencyMs}ms)` : ''}${backendStatus.error ? ` | ${backendStatus.error}` : ''}`
                        : 'Backend: unknown'
                    }
                  >
                    <span className={styles.backendDot} />
                    {backendStatus.ok ? `API ${backendStatus.latencyMs != null ? `${backendStatus.latencyMs}ms` : 'up'}` : 'API down'}
                  </span>
                </div>
                <div className={styles.chatHeaderActions}>
                  <button className={styles.iconBtn} onClick={() => setReadinessOpen((v) => !v)} title="System Readiness">●</button>
                  <button
                    className={styles.iconBtn}
                    onClick={() => setTraceOpen(true)}
                    title={traceId ? 'Decision Trace' : 'Decision Trace (opens after a routed decision creates a trace id)'}
                    aria-label="Decision Trace"
                  >
                    <GearIcon />
                  </button>
                  <button className={styles.iconBtn} title="Pop-out"><DetachIcon /></button>
                  <button className={styles.iconBtn} onClick={() => { setChatOpen(false); switchRightPanelMode('none'); }} title="Close"><CloseIcon /></button>
                </div>
              </div>

              <div
                className={styles.chatBody}
                ref={chatBodyRef}
                onDrop={handleDrop}
                onDragOver={(e) => e.preventDefault()}
                onPaste={handlePaste}
              >
                {messages.length === 0 && (
                  <div className={styles.welcome}>
                    <p>Hi! I'm your ShopSquire assistant.</p>
                    <p>Ask me about laptops, compare models, or get recommendations.</p>
                    <p className={styles.welcomeHint}>You can also paste or drag images into this chat.</p>
                    <div className={styles.quickActions}>
                      <button onClick={() => handleQuickAction('Show gaming laptops under $2000')}>Gaming</button>
                      <button onClick={() => handleQuickAction('Budget laptops under $1000')}>Budget</button>
                      <button onClick={() => handleQuickAction('Compare top MacBooks')}>Compare</button>
                      <button onClick={() => handleQuickAction('Show detailed specs for workstations')}>Specs</button>
                    </div>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`${styles.message} ${styles[msg.role]}`}>
                    <div className={styles.messageContent}>
                      {/* Inline image thumbnails for user messages */}
                      {msg.images && msg.images.length > 0 && (
                        <div className={styles.msgImageStrip}>
                          {msg.images.map((src, j) => (
                            <img key={j} src={src} alt={`attachment ${j + 1}`} className={styles.msgThumb} />
                          ))}
                        </div>
                      )}
                      {msg.role === 'assistant'
                        ? String(msg.content || '').split(/\n\n+/).filter(Boolean).map((para, pi) => {
                            const isWarn = /^\s*(⚠️|\[security\])/i.test(para);
                            return (
                              <div key={pi} className={isWarn ? styles.msgSecurity : styles.msgPara}>
                                <InlineMessageText text={para.trim()} />
                              </div>
                            );
                          })
                        : msg.content}
                      {/* Voice badge */}
                      {msg.voiceUsed && <span className={styles.voiceBadge} title="Sent via voice">🎤</span>}
                      {/* Complexity badge — dev-only hint; hidden from pilot buyers (showDebugBadges gate) */}
                      {showDebugBadges && msg.complexity && (
                        <span
                          className={styles.complexityBadge}
                          title={`Complexity ${msg.complexity.score}/10 · Tier: ${msg.complexity.tier} · Model: ${msg.complexity.model}`}
                          style={{ display: 'block', fontSize: '0.62em', opacity: 0.35, marginTop: 4, letterSpacing: '0.02em' }}
                        >
                          {msg.complexity.tier} · {msg.complexity.model?.split(':')[0]}
                        </span>
                      )}
                      {msg.agentStepsReadable && msg.agentStepsReadable.length > 0 && (
                        <details style={{ marginTop: 8, fontSize: '0.78em', opacity: 0.72 }}>
                          <summary style={{ cursor: 'pointer', userSelect: 'none' }}>How I answered this</summary>
                          <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                            {msg.agentStepsReadable.map((step, si) => (
                              <li key={si} style={{ marginBottom: 2 }}>{step}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                      {i === messages.length - 1 && msg.nextQuestions
                        && msg.nextQuestions.some(isActionableBuyerQuestion) && (
                        /* ONE framed "narrow this down" card instead of a loose chip wall (demo
                           feedback: "looks clunky — maybe a separate output box"). Question text is a
                           heading, its options are compact chips beneath; capped at 2 questions. */
                        <div data-testid="nqe-card" style={{
                          marginTop: 10, border: '1px solid #e5e7eb', background: '#f9fafb',
                          borderRadius: 10, padding: '10px 12px',
                        }}>
                          <div style={{ fontSize: 12, fontWeight: 700, color: '#4f46e5', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
                            Help me narrow this down
                          </div>
                          {msg.nextQuestions.filter(isActionableBuyerQuestion).slice(0, 2).map((nq, qi) => (
                            <div key={nq.id} style={{ marginTop: qi > 0 ? 8 : 0 }}>
                              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                                <button
                                  type="button"
                                  onClick={() => handleQuickAction(nq.text)}
                                  style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                                           font: 'inherit', fontSize: 13, fontWeight: 600, color: '#1f2937', textAlign: 'left' }}
                                >
                                  {nq.text}
                                </button>
                                {nq.why_hint && (
                                  <button type="button" className={styles.hintBtn} title={nq.why_hint}
                                          style={{ fontSize: 11 }}>
                                    why?
                                  </button>
                                )}
                              </div>
                              {Array.isArray(nq.options) && nq.options.length > 0 && (
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 5 }}>
                                  {/* cap at 3 option chips per question — the full list was a clunky wall
                                      (a business question surfaced 5-6). Top 3 keeps the card scannable. */}
                                  {nq.options.slice(0, 3).map((opt) => (
                                    <button
                                      key={`${nq.id}:${opt.id}`}
                                      type="button"
                                      className={styles.filterBtn}
                                      onClick={() => handleNqeOptionSelect(nq, opt)}
                                    >
                                      {opt.label}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    {/* Disambiguation buttons for assistant */}
                    {msg.disambiguation && msg.disambiguationOptions && msg.disambiguationOptions.length > 0 && (
                      <DisambiguationButtons options={msg.disambiguationOptions} onSelect={handleDisambiguationSelect} />
                    )}
                    {msg.webConsentPrompt && (
                      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                        <button type="button" className={styles.filterBtn} style={{ border: '1.5px solid #f59e0b' }}
                          onClick={() => {
                            const wq = msg.webConsentPrompt!.query;
                            setMessages(prev => prev.map(m => m === msg ? { ...m, webConsentPrompt: undefined } : m));
                            void handleSend({ queryOverride: wq, externalResearchConsent: true });
                          }}>
                          🌐 Check approved sources
                        </button>
                        <button type="button" className={styles.filterBtn}
                          onClick={() => {
                            const wq = msg.webConsentPrompt!.query;
                            setMessages(prev => prev.map(m => m === msg ? { ...m, webConsentPrompt: undefined } : m));
                            void handleSend({ queryOverride: wq, externalResearchConsent: false });
                          }}>
                          Use store data only
                        </button>
                      </div>
                    )}
                    {msg.evidence && Array.isArray(msg.evidence.citations) && msg.evidence.citations.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8, alignItems: 'center' }}>
                        <span style={{ fontSize: 11, color: '#6b7280' }}>Sources:</span>
                        {citationChips(msg.evidence).map((chip) => (
                          <button
                            key={chip.key}
                            type="button"
                            className={styles.filterBtn}
                            style={chip.trusted ? undefined : { border: '1.5px solid #f59e0b' }}
                            title={chip.trusted ? 'Trusted store record — open the Evidence tab' : 'External evidence (verified, never authority) — open the Evidence tab'}
                            onClick={() => { setTraceEvidence(msg.evidence); setTraceInitialTab('evidence'); setTraceOpen(true); }}
                          >
                            {chip.icon} {chip.label}
                          </button>
                        ))}
                      </div>
                    )}
                    {msg.undoClear && msg.undoClear.items.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <button
                          type="button"
                          className={styles.filterBtn}
                          onClick={() => {
                            const items = msg.undoClear!.items;
                            // consume: drop the chip so it can't be double-applied, then restore
                            setMessages(prev => prev.map(m => m === msg ? { ...m, undoClear: undefined } : m));
                            void restoreClearedItems(items);
                          }}
                          title="Put the cleared items back"
                        >
                          ↩️ Undo — restore {msg.undoClear.items.length} item(s)
                        </button>
                      </div>
                    )}
                    {msg.undoServer && (
                      <div style={{ marginTop: 8 }}>
                        <button
                          type="button"
                          className={styles.filterBtn}
                          onClick={() => { void undoServerSnapshot(msg); }}
                          title="Restore the cart from before that change (server snapshot)"
                        >
                          ↩️ Undo that cart change
                        </button>
                      </div>
                    )}
                    {msg.cartConfirm && (
                      <PendingCartChangeCard
                        plan={msg.cartConfirm}
                        cartItems={(cart?.items || []) as any[]}
                        onConfirm={() => { void confirmCartPlan(msg); }}
                        onDismiss={() => { void dismissCartPlan(msg); }}
                      />
                    )}
                    {msg.buyerRequirementClaims && (
                      <BuyerRequirementReviewCard
                        claims={msg.buyerRequirementClaims}
                        onAccept={msg.buyerRequirementProposal
                          ? (claimIds, choice, corrections) => acceptBuyerRequirementProposal(msg, claimIds, choice, corrections)
                          : undefined}
                      />
                    )}
                    {msg.buyerClaimReconciliation && (
                      <BuyerClaimReconciliationCard rows={msg.buyerClaimReconciliation} />
                    )}
                    {msg.cartPlanStatus && (
                      <div style={{ marginTop: 8, fontSize: 12, color: '#92400e' }}>{msg.cartPlanStatus}</div>
                    )}
                    {msg.affordabilityResolution && (
                      <AffordabilityResolutionCard
                        resolution={msg.affordabilityResolution}
                        onChoose={(choice) => chooseAffordabilityResolution(msg, choice)}
                      />
                    )}
                  </div>
                ))}
                {(isThinking || imageRoutingInFlight) && (
                  <div className={`${styles.message} ${styles.assistant}`}>
                    <div className={`${styles.messageContent} ${styles.thinkingBubble}`}>
                      {streamAcknowledgement ? (
                        <span role="status" data-testid="stream-acknowledgement">{streamAcknowledgement}</span>
                      ) : (
                        <>
                          <span className={styles.thinkingDot}>.</span>
                          <span className={styles.thinkingDot}>.</span>
                          <span className={styles.thinkingDot}>.</span>
                        </>
                      )}
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Composer Card */}
              <div className={styles.chatFooter}>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
                  <button
                    type="button"
                    className={styles.filterBtn}
                    aria-pressed={temporaryChat}
                    data-testid="temporary-chat-toggle"
                    title="Temporary chat is not written to conversation history or memory"
                    onClick={() => {
                      const next = !temporaryChat;
                      setTemporaryChat(next);
                      setConversationEpoch(rotateConversationEpoch());
                      setMessages([]);
                      setConfirmedSlots({});
                    }}
                  >
                    {temporaryChat ? 'Temporary chat: on' : 'Temporary chat: off'}
                  </button>
                </div>
                {/* Thumbnail strip for attached images */}
                {attachedThumbs.length > 0 && (
                  <div className={styles.thumbStrip}>
                    {attachedThumbs.map((src, i) => (
                      <div key={i} className={styles.thumbWrap}>
                        <img src={src} alt={`attached ${i + 1}`} className={styles.thumbImg} />
                        <button className={styles.thumbRemove} onClick={() => removeAttachment(i)} title="Remove">&times;</button>
                      </div>
                    ))}
                  </div>
                )}
                {attachedFiles.some((file) => !file.type.startsWith('image/')) && (
                  <div className={styles.thumbStrip} data-testid="attached-requirement-documents">
                    {attachedFiles.map((file, index) => !file.type.startsWith('image/') ? (
                      <div key={`${file.name}-${file.lastModified}-${index}`} className={styles.thumbWrap}>
                        <span aria-label={`Attached requirements document ${file.name}`}>{file.name}</span>
                        <button
                          className={styles.thumbRemove}
                          onClick={() => removeAttachment(index)}
                          title={`Remove ${file.name}`}
                          aria-label={`Remove ${file.name}`}
                        >
                          &times;
                        </button>
                      </div>
                    ) : null)}
                  </div>
                )}
                <div className={styles.composerRow}>
                  <AttachmentButton onFiles={handleAttach} className={styles.inputIconBtn} />
                  <textarea
                    ref={textareaRef}
                    className={styles.chatInput}
                    aria-label="Message ShopSquire Assistant"
                    placeholder={imageRoutingInFlight ? "Analyzing image..." : (stt.isRecording ? "Listening..." : "Type your message...")}
                    value={inputValue}
                    onChange={(e) => { setInputValue(e.target.value); handleTextareaInput(); }}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    rows={1}
                  />
                  <button
                    className={`${styles.inputIconBtn} ${stt.isRecording ? styles.recording : ''}`}
                    onClick={handleMicClick}
                    title={stt.isRecording ? 'Click to stop recording' : 'Voice input'}
                    aria-label={stt.isRecording ? 'Stop voice input' : 'Start voice input'}
                  >
                    <MicIcon />
                    {stt.whisperPending && <span className={styles.whisperDot} />}
                  </button>
                  <button
                    className={styles.sendBtn}
                    onClick={() => handleSend()}
                    disabled={isThinking || imageRoutingInFlight}
                    aria-label="Send message"
                  ><SendIcon /></button>
                </div>
                {/* NQE questions render inline in the assistant message (with option chips) — the old
                    sticky bottom bar duplicated them ("looks messy"), so it was removed. */}
                {receiptRequested && (
                  <div style={{ marginTop: 8, fontSize: 12, color: '#9a3412' }}>
                    Proof requested: use the paperclip to upload a receipt, order confirmation, or a photo of the serial number label.
                  </div>
                )}
              </div>
            </div>

            {/* Right Panel */}
            {hasRightPanel && (
              <div className={styles.rightPanel}>
                <div className={styles.rightHeader}>
                  <div className={styles.rightHeaderTitleRow}>
                    {rightPanelPrevMode && rightPanelPrevMode !== rightPanelMode && (
                      <button className={styles.panelBackBtn} onClick={handleRightPanelBack} type="button" title="Back to previous panel">
                        ← Back
                      </button>
                    )}
                    <span>
                      {rightPanelMode === 'none' && fulfilmentCase
                        ? 'Procurement'
                        : rightPanelMode === 'compare'
                        ? 'Comparison'
                        : rightPanelMode === 'list'
                          ? 'Detailed Specs'
                          : rightPanelContract?.mode === 'support'
                            ? 'Support Next Steps'
                          : rightPanelMode === 'cv'
                            ? 'CV Triage'
                          : rightPanelMode === 'cart'
                            ? 'Cart & Upsell'
                            : rightPanelMode === 'visual_search'
                              ? 'Visual Search'
                          : rightPanelMode === 'image_context'
                                ? 'Image Context'
                                : productShelves?.shelves?.length
                                  ? `${productShelves.evidence_status === 'researched' ? 'Researched shortlist' : 'Provisional shortlist'} — ${new Set(productShelves.shelves.flatMap((shelf) => [...shelf.initial, ...shelf.next_page].map((item) => item.identity_key))).size} configurations`
                                  : `Found ${filteredDisplayProducts.length} products`}
                    </span>
                  </div>
                  {rightPanelMode !== 'none' && (
                    <div className={styles.viewToggle}>
                      <button className={viewMode === 'grid' ? styles.active : ''} onClick={() => setViewMode('grid')}><GridIcon /></button>
                      <button className={viewMode === 'list' ? styles.active : ''} onClick={() => setViewMode('list')}><ListIcon /></button>
                    </div>
                  )}
                </div>
                {readinessOpen && (
                  <div className={styles.readinessPanel}>
                    <div className={styles.readinessTitle}>System Readiness {readyzLoading ? '(checking...)' : ''}</div>
                    {(readyz?.components ? Object.entries(readyz.components) : []).map(([name, comp]) => (
                      <div key={name} className={styles.readinessRow}>
                        <span>{name}</span>
                        <span className={comp?.status === 'ready' ? styles.readyOk : styles.readyBad}>{comp?.status || 'unknown'}</span>
                      </div>
                    ))}
                    {Array.isArray(readyz?.reasons) && readyz?.reasons.length > 0 && (
                      <div className={styles.readinessReasons}>Issues: {readyz.reasons.join(', ')}</div>
                    )}
                    {operatorMetrics && (
                      <div className={styles.operatorMetrics}>
                        <div className={styles.operatorMetricTitle}>Last Recommend</div>
                        <div className={styles.readinessRow}>
                          <span>Catalog cache</span>
                          <span
                            className={
                              operatorMetrics.catalogProfileCacheHit == null
                                ? styles.muted
                                : operatorMetrics.catalogProfileCacheHit
                                  ? styles.readyOk
                                  : styles.readyBad
                            }
                          >
                            {operatorMetrics.catalogProfileCacheHit == null ? '--' : operatorMetrics.catalogProfileCacheHit ? 'hit' : 'miss'}
                          </span>
                        </div>
                        {operatorMetrics.catalogProfileMs != null && (
                          <div className={styles.readinessRow}>
                            <span>Catalog profile</span>
                            <span>{Math.round(Number(operatorMetrics.catalogProfileMs) || 0)}ms</span>
                          </div>
                        )}
                        {operatorMetrics.ollamaSummaryMs != null && (
                          <div className={styles.readinessRow}>
                            <span>Ollama summary</span>
                            <span>{Math.round(Number(operatorMetrics.ollamaSummaryMs) || 0)}ms</span>
                          </div>
                        )}
                        {operatorMetrics.routeTotalMs != null && (
                          <div className={styles.readinessRow}>
                            <span>Total route</span>
                            <span>{Math.round(Number(operatorMetrics.routeTotalMs) || 0)}ms</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <div className={styles.rightBody}>
                  {ambiguityExploration && (
                    <AmbiguityExplorationPanel
                      exploration={ambiguityExploration}
                      onResearch={() => { void researchAmbiguousShoppingCase(); }}
                      onUpload={() => document.querySelector<HTMLInputElement>("input[type='file']:not([capture])")?.click()}
                      onResolveEvidenceSource={resolveBuyerEvidenceSource}
                      onEnterSpecifications={() => document.querySelector<HTMLTextAreaElement>("textarea[placeholder='Type your message...']")?.focus()}
                    />
                  )}
                  {productShelves && <ProductShelvesPanel
                    projection={productShelves}
                    onPropose={ambiguityExploration?.status === 'researched' ? proposeResearchedProduct : undefined}
                  />}
                  {supplierContinuation && <SupplierContinuationCard
                    journey={supplierContinuation}
                    onAssess={(deadlineDays) => { void assessSupplierContinuation(deadlineDays); }}
                    onSelectChoice={(choiceId) => { void selectSupplierContinuation(choiceId); }}
                    onSelectOffer={(offerId) => setSupplierContinuation((current) => current ? {
                      ...current, selectedOfferId: offerId,
                    } : current)}
                    onConfirm={() => { void confirmSupplierContinuation(); }}
                    onBack={() => setSupplierContinuation((current) => current ? {
                      ...current, selectedChoice: undefined, selectionId: undefined,
                      offers: undefined, selectedOfferId: undefined, status: 'review', error: undefined,
                      selectionKey: `portfolio-select-${crypto.randomUUID()}`,
                      confirmationKey: `portfolio-confirm-${crypto.randomUUID()}`,
                    } : current)}
                    onDismiss={() => setSupplierContinuation(null)}
                  />}
                  {rightPanelContract?.emphasis?.applied && rightPanelContract.emphasis.text && (
                    <div
                      data-testid="right-panel-emphasis"
                      data-variant={rightPanelContract.emphasis.key || rightPanelContract.emphasis.variant}
                      style={{
                        margin: '0 0 10px', padding: '8px 12px', borderRadius: 8,
                        border: '1px solid rgba(37,99,235,0.25)', background: 'rgba(37,99,235,0.06)',
                        color: '#1d4ed8', fontSize: 13, fontWeight: 600,
                      }}
                    >
                      {rightPanelContract.emphasis.text}
                    </div>
                  )}
                  {multiIntent && (multiIntent.plan?.length ?? 0) > 0 && (
                    <div className={styles.procurementPanelSlot}>
                      <MultiIntentCard
                        plan={multiIntent}
                        onAmendQty={async (sku, qty) => {
                          await setCartQty(sku, qty, true);
                          // Amendment applied → dismiss the card and show the updated cart, so the
                          // stale plan/prose (e.g. "…25") isn't left hanging beside the new quantity.
                          setMultiIntent(null);
                          switchRightPanelMode('cart');
                        }}
                        onAddItem={(sku, qty) => addToCart(sku, qty)}
                        onDismiss={() => setMultiIntent(null)}
                      />
                    </div>
                  )}
                  {bulkAlternatives.length > 0 && !(sourcingIntent && (sourcingIntent.lines?.length ?? 0) > 0 && !fulfilmentCase) && (
                    <div className={styles.procurementPanelSlot}>
                      <BulkAlternatives options={bulkAlternatives} />
                    </div>
                  )}
                  {fulfilmentCase && (
                    <div className={styles.procurementPanelSlot}>
                      <FulfilmentOptions caseSummary={fulfilmentCase} uid={uid} pollMs={4000} />
                    </div>
                  )}
                  {!fulfilmentCase && sourcingIntent && (sourcingIntent.lines?.length ?? 0) > 0 && (
                    <div className={styles.procurementPanelSlot}>
                      {/* order_id = the server-minted Procurement Request (PR) id — STABLE across amendments
                          (re-confirm supersedes the SAME order group, no duplicate cases) and DISTINCT for a
                          genuinely new cart (closes cross-order contamination). Falls back to a session id only
                          if the backend didn't mint one. traceId stays separate for the decision-trace link. */}
                      <SourcingIntentCard intent={sourcingIntent} uid={uid}
                                          orderId={sourcingIntent.pr_id || `cart-${uid}`}
                                          traceId={sourcingTraceId || traceId || undefined} />
                    </div>
                  )}
                  {rightPanelContract?.image_untrusted && (
                    <div className={styles.tierBlock}>
                      <div className={styles.tierTitle}>
                        Image Security: {rightPanelContract?.security_route || 'degraded'}
                      </div>
                      <div className={styles.tierExplain}>
                        {rightPanelContract?.security_summary || 'Image was flagged. Recommendations are running in text-only fallback mode.'}
                      </div>
                    </div>
                  )}
                  {Array.isArray(rightPanelContract?.anchor_sections) && rightPanelContract!.anchor_sections!.length > 0 && (
                    <div className={styles.tierPanel}>
                      {(rightPanelContract!.anchor_sections || []).map((section, idx) => (
                        <div key={String(section?.anchor_id || idx)} className={styles.tierBlock}>
                          <div className={styles.tierTitle}>{section?.title || `Image ${idx + 1}`}</div>
                          <div className={styles.tierCarousel}>
                            {(section?.top_products || []).slice(0, 3).map((p) => (
                              <article key={`anchor-${idx}-${p.sku}`} className={styles.tierCard}>
                                <div className={styles.tierName}>{p.name}</div>
                                <div className={styles.tierPrice}>{formatPrice(p)}</div>
                                <button className={styles.tierAdd} onClick={() => addToCart(p.sku)}>Add</button>
                              </article>
                            ))}
                          </div>
                          {section?.summary && <div className={styles.tierExplain}>{section.summary}</div>}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Procurement-truth advisory: a work query with no clean fleet match → recommend sourcing. */}
                  {rightPanelContract?.fleet_advisory?.suggest_procurement && rightPanelContract.fleet_advisory.message && (
                    <div data-testid="fleet-advisory" role="alert"
                         style={{ margin: '8px 0', padding: '8px 12px', borderRadius: 8,
                                  border: '1px solid #f59e0b', background: '#fffbeb', color: '#92400e', fontSize: 13 }}>
                      <strong>Closest matches shown.</strong> {rightPanelContract.fleet_advisory.message}
                    </div>
                  )}

                  {/* BACKEND choice-lanes (evidence-driven) — render these when present; map each lane's
                      skus to the full product cards. Falls back to the frontend heuristic lanes below. */}
                  {(['grid', 'list', 'compare'] as RightPanelMode[]).includes(rightPanelMode)
                    && !recommendationShelf
                    && filteredDisplayProducts.length > 0
                    && Array.isArray(rightPanelContract?.device_lanes) && rightPanelContract!.device_lanes!.length > 0 && (
                    <div className={styles.deviceLanePanel} data-testid="backend-device-lanes">
                      {rightPanelContract!.device_lanes!.map((lane) => {
                        const bySku = new Map(filteredDisplayProducts.map((p) => [p.sku, p]));
                        const items = (lane.skus || []).map((s) => bySku.get(s)).filter(Boolean) as Product[];
                        if (!items.length) return null;
                        return (
                          <section key={`blane-${lane.key}`} className={styles.deviceLaneBlock}
                                   data-testid="device-lane" data-lane={lane.key} data-primary={lane.primary ? '1' : '0'}>
                            <div className={styles.deviceLaneHeader}>
                              <div className={styles.deviceLaneTitle}
                                   style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                <span>{lane.title}</span>
                                {lane.non_primary && (
                                  <span data-testid="lane-non-primary"
                                        style={{ fontSize: 11, fontWeight: 700, padding: '1px 6px',
                                                 borderRadius: 4, background: '#fef3c7', color: '#92400e' }}>
                                    not a primary pick
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className={styles.deviceLaneCarousel}>
                              {items.slice(0, 3).map((p) => (
                                <article key={`blane-card-${lane.key}-${p.sku}`} className={styles.deviceLaneCard}>
                                  {p.image_url ? (
                                    <img src={p.image_url} alt={p.name} className={styles.deviceLaneImg} />
                                  ) : (
                                    <div className={styles.deviceLaneImgPlaceholder}>No image</div>
                                  )}
                                  <div className={styles.deviceLaneName}>{p.name}</div>
                                  <div className={styles.deviceLanePrice}>{formatPrice(p)}</div>
                                  <button className={styles.deviceLaneAdd} onClick={() => addToCart(p.sku)}>Add</button>
                                </article>
                              ))}
                            </div>
                            {lane.explanation && <div className={styles.deviceLaneSummary}>{lane.explanation}</div>}
                          </section>
                        );
                      })}
                    </div>
                  )}

                  {/* Heuristic lane fallback — only when the backend provided no device_lanes. */}
                  {(['grid', 'list', 'compare'] as RightPanelMode[]).includes(rightPanelMode)
                    && !recommendationShelf
                    && filteredDisplayProducts.length > 0
                    && !(Array.isArray(rightPanelContract?.device_lanes) && rightPanelContract!.device_lanes!.length > 0) && (
                    <div className={styles.deviceLanePanel}>
                      {(['windows', 'macbook', 'tablet_chromebook'] as DeviceLane[]).map((lane) => {
                        const items = laneBuckets[lane] || [];
                        if (!items.length) return null;
                        return (
                          <section key={`lane-${lane}`} className={styles.deviceLaneBlock}>
                            <div className={styles.deviceLaneHeader}>
                              <div className={styles.deviceLaneTitle}>{laneTitle(lane)}</div>
                              <button
                                className={styles.deviceLaneExpand}
                                onClick={() => setExpandedLane(lane)}
                                type="button"
                              >
                                Expand
                              </button>
                            </div>
                            <div className={styles.deviceLaneCarousel}>
                              {items.slice(0, 3).map((p) => (
                                <article key={`lane-card-${lane}-${p.sku}`} className={styles.deviceLaneCard}>
                                  {p.image_url ? (
                                    <img src={p.image_url} alt={p.name} className={styles.deviceLaneImg} />
                                  ) : (
                                    <div className={styles.deviceLaneImgPlaceholder}>No image</div>
                                  )}
                                  <div className={styles.deviceLaneName}>{p.name}</div>
                                  <div className={styles.deviceLanePrice}>{formatPrice(p)}</div>
                                  <button className={styles.deviceLaneAdd} onClick={() => addToCart(p.sku)}>Add</button>
                                </article>
                              ))}
                            </div>
                            <div className={styles.deviceLaneSummary}>
                              {laneSummary(
                                lane,
                                items,
                                rightPanelContract?.budget_status,
                                visualSearchQuery || String(localStorage.getItem('shopsquire_last_user_query') || ''),
                              )}
                            </div>
                          </section>
                        );
                      })}
                    </div>
                  )}

                  {expandedLane && (
                    <div className={styles.expandedLanePanel}>
                      <div className={styles.expandedLaneHeader}>
                        <div className={styles.expandedLaneTitle}>
                          More {laneTitle(expandedLane)} ({expandedLaneProducts.length})
                        </div>
                        <button className={styles.iconBtn} onClick={() => setExpandedLane(null)}>Close</button>
                      </div>
                      <ProductGrid
                        products={expandedLaneProducts}
                        onAdd={addToCart}
                        onWhy={handleWhyProduct}
                        viewMode="detailed"
                      />
                    </div>
                  )}

                  {Array.isArray((rightPanelContract as any)?.parallel_agents) && (rightPanelContract as any).parallel_agents.length > 0 && (
                    <div className={styles.supportAgents} style={{ background: (rightPanelContract as any).image_flagged ? 'rgba(239,68,68,0.08)' : undefined, borderRadius: 8, marginBottom: 8, padding: '8px 12px' }}>
                      {(rightPanelContract as any).image_flagged && (
                        <div style={{ color: '#ef4444', fontWeight: 700, fontSize: 13, marginBottom: 4 }}>
                          ⚠️ Image flagged — security agents engaged, showing text-only results
                        </div>
                      )}
                      <div className={styles.tierTitle}>Parallel agents running</div>
                      <div className={styles.tagRow}>
                        {(rightPanelContract as any).parallel_agents.map((a: any) => (
                          <span key={String(a)} className={styles.quickChip} style={{ background: (rightPanelContract as any).image_flagged ? '#fef2f2' : undefined, color: (rightPanelContract as any).image_flagged ? '#dc2626' : undefined }}>{String(a)}</span>
                        ))}
                      </div>
                      {(rightPanelContract as any).security_matrix && (
                        <div style={{ marginTop: 6, fontSize: 12, color: '#6b7280' }}>
                          <strong>Security matrix:</strong>{' '}
                          {[(rightPanelContract as any).security_matrix.verdict, ...((rightPanelContract as any).security_matrix.owasp || []).slice(0, 2)].filter(Boolean).join(' · ')}
                          {' '}— <button style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer', padding: 0, fontSize: 12 }} onClick={() => setTraceOpen(true)}>View full trace ↗</button>
                        </div>
                      )}
                    </div>
                  )}
                  {rightPanelContract?.mode === 'shopping' && rightPanelContract?.show_tiers && (
                    <div className={styles.tierPanel}>
                      <div className={styles.tierBlock}>
                        <div className={styles.tierLabel}>
                          {rightPanelContract.budget_status === 'low'
                            ? 'Budget is tight - showing best value options first'
                            : 'Showing budget-fit + performance-fit options'}
                        </div>
                        <div className={styles.tierPills}>
                          <button
                            onClick={() => setTierFilter('lower')}
                            className={tierFilter === 'lower' ? styles.tierPillActive : styles.tierPill}
                          >
                            Budget fit ({rightPanelContract.lower_tier?.items?.length ?? 0})
                          </button>
                          <button
                            onClick={() => setTierFilter('higher')}
                            className={tierFilter === 'higher' ? styles.tierPillActive : styles.tierPill}
                          >
                            Performance fit ({rightPanelContract.higher_tier?.items?.length ?? 0})
                          </button>
                          <button
                            onClick={() => setTierFilter('all')}
                            className={tierFilter === 'all' ? styles.tierPillActive : styles.tierPill}
                          >
                            All results
                          </button>
                        </div>
                        {tierFilter !== 'all' && (
                          <div className={styles.tierExplanation}>
                            {tierFilter === 'lower'
                              ? rightPanelContract.lower_tier?.explanation
                              : rightPanelContract.higher_tier?.explanation}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {rightPanelContract?.mode === 'support' && (
                    <div className={styles.supportPanel}>
                      <div className={styles.supportSummary}>{rightPanelContract.summary || 'Support workflow is active.'}</div>
                      {Array.isArray((rightPanelContract as any).support_cards) && (rightPanelContract as any).support_cards.length > 0 && (
                        <div className={styles.supportCards}>
                          {(rightPanelContract as any).support_cards.map((c: any) => (
                            <article key={String(c?.id || c?.title || Math.random())} className={styles.supportCard}>
                              <div className={styles.supportCardTitle}>{String(c?.title || 'Support card')}</div>
                              <div className={styles.supportCardStatus}>Status: {String(c?.status || 'unknown')}</div>
                              <div className={styles.supportCardMessage}>{String(c?.message || '')}</div>
                              {c?.order_ref && <div className={styles.supportCardStatus}>Order ref: {String(c.order_ref)}</div>}
                            </article>
                          ))}
                        </div>
                      )}
                      {Array.isArray((rightPanelContract as any).faq_playbooks) && (rightPanelContract as any).faq_playbooks.length > 0 && (
                        <div className={styles.supportFaq}>
                          <div className={styles.tierTitle}>FAQ Playbooks</div>
                          {(rightPanelContract as any).faq_playbooks.map((pb: any) => (
                            <div key={String(pb?.id || pb?.title || Math.random())} className={styles.supportFaqItem}>
                              <div className={styles.supportFaqTitle}>{String(pb?.title || 'Playbook')}</div>
                              <ul>
                                {Array.isArray(pb?.steps) ? pb.steps.slice(0, 4).map((s: any, i: number) => <li key={`${pb?.id || 'pb'}-${i}`}>{String(s)}</li>) : null}
                              </ul>
                            </div>
                          ))}
                        </div>
                      )}
                      {Array.isArray((rightPanelContract as any).parallel_agents) && (rightPanelContract as any).parallel_agents.length > 0 && (
                        <div className={styles.supportAgents}>
                          <div className={styles.tierTitle}>Parallel agents</div>
                          <div className={styles.tagRow}>
                            {(rightPanelContract as any).parallel_agents.map((a: any) => (
                              <span key={String(a)} className={styles.quickChip}>{String(a)}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {rightPanelMode === 'faq' ? (
                    <RightPanelExtras mode="faq" />
                  ) : rightPanelMode === 'visual_search' ? (
                    <RightPanelExtras mode="visual_search" initialImageContexts={imageTriageContexts} userQuery={visualSearchQuery} canonicalProducts={canonicalImageProducts} canonicalSummary={canonicalImageSummary} onTraceId={(tid) => setTraceId(normalizeTraceId(tid))} onClarify={(q) => { if (isThinking) return; setInputValue(q); handleSend({ queryOverride: q }); }} onAdd={addToCart} />
                  ) : rightPanelMode === 'image_context' ? (
                    <RightPanelExtras mode="image_context" initialImageContexts={imageTriageContexts} userQuery={visualSearchQuery} canonicalProducts={canonicalImageProducts} canonicalSummary={canonicalImageSummary} onTraceId={(tid) => setTraceId(normalizeTraceId(tid))} onClarify={(q) => { if (isThinking) return; setInputValue(q); handleSend({ queryOverride: q }); }} onAdd={addToCart} />
                  ) : rightPanelMode === 'cv' ? (
                    <RightPanelExtras
                      mode="cv"
                      autoIssueType={cvAutoIssueType}
                      initialImages={cvPrefillImages}
                      onEscalate={(payload) => {
                        const incId = payload?.incident_id;
                        if (!incId) {
                          setMessages(prev => [...prev, {
                            role: 'assistant',
                            content: 'Escalation failed: incident id was not returned by /api/v1/incidents/escalate.',
                            timestamp: new Date(),
                          }]);
                          return;
                        }
                        setEscalationIncidentId(incId);
                        if (payload?.buyer_token) setEscalationBuyerToken(String(payload.buyer_token)); else setEscalationBuyerToken(null);
                        setEscalationOpen(true);
                        setMessages(prev => [...prev, { role: 'assistant', content: 'Escalated to human review. Opening escalation room...', timestamp: new Date() }]);
                      }}
                      onTraceId={(tid) => setTraceId(normalizeTraceId(tid))}
                      onResult={(cvRes: any) => {
                        setCvPrefillImages([]);
                        maybeAppendCvSecurityNote(cvRes);
                      }}
                    />
                  ) : rightPanelMode === 'compare' && filteredDisplayProducts.length > 0 ? (
                    <div className={styles.compareTable}>
                      <table>
                        <thead>
                          <tr>
                            <th>Feature</th>
                            {filteredDisplayProducts.slice(0, 3).map(p => <th key={p.sku}>{p.name.split(' ').slice(0, 3).join(' ')}</th>)}
                          </tr>
                        </thead>
                        <tbody>
                          <tr><td>Price</td>{filteredDisplayProducts.slice(0, 3).map(p => <td key={p.sku}>{formatPrice(p)}</td>)}</tr>
                          {['Display', 'Processor', 'RAM', 'Storage', 'Graphics'].map((feat, i) => (
                            <tr key={feat}>
                              <td>{feat}</td>
                              {filteredDisplayProducts.slice(0, 3).map(p => <td key={p.sku}>{(p.features || [])[i + 1]?.replace(/^[^:]+:\s*/, '') || '-'}</td>)}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    rightPanelMode === 'cart' ? (<>
                      {cart?.undo?.available && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                                      background: '#fef3c7', borderRadius: 8, margin: '0 0 8px 0', fontSize: 13 }}>
                          <span>Undo available for your last cart change ({cart.undo.count} prior line item(s)).</span>
                          <button type="button" className={styles.filterBtn}
                            onClick={async () => {
                              try {
                                const j = await undoCartClear(uid);
                                setCart(j);
                              } catch { /* snapshot expired — banner disappears on next refresh */ }
                            }}>
                            ↩️ Restore
                          </button>
                        </div>
                      )}
                      <CartPanel
                        uid={uid}
                        cart={cart}
                        onRefresh={refreshCart}
                        onRemove={removeFromCart}
                        onClear={clearCartAll}
                        onAdd={addToCart}
                        onSetQty={setCartQty}
                        traceId={traceId || sourcingTraceId}
                        onTraceId={(tid) => setTraceId(normalizeTraceId(tid))}
                        onSourcingTraceId={(tid) => setSourcingTraceId(normalizeTraceId(tid))}
                        priorSkus={priorCartSkus}
                        onClearPrior={clearPriorCartItems}
                        sourcingRequirements={{
                          ...(sourcingIntent?.requirements || {}),
                          ...procurementRequirements,
                        }}
                        sourcingOrderId={sourcingIntent?.pr_id}
                        confirmedSourcingOrderId={confirmedSourcingOrderId}
                        onConfirmedSourcingOrderId={setConfirmedSourcingOrderId}
                      />
                    </>) : recommendationShelf && ['grid', 'list'].includes(rightPanelMode) ? (
                      <RecommendationShelf
                        shelf={recommendationShelf}
                        onAdd={addToCart}
                        onWhy={handleWhyProduct}
                      />
                    ) : !productShelves && filteredDisplayProducts.length === 0 && ['grid', 'list', 'compare'].includes(rightPanelMode) ? (
                      <div className={styles.emptyProductState}>
                        <div className={styles.emptyProductIcon}>🔍</div>
                        <div className={styles.emptyProductTitle}>No products found</div>
                        <div className={styles.emptyProductHint}>Try adjusting your budget, use-case, or brand filter. I can help — just ask!</div>
                      </div>
                    ) : (
                      <ProductGrid
                        products={filteredDisplayProducts}
                        onAdd={addToCart}
                        onWhy={handleWhyProduct}
                        viewMode={viewMode === 'list' || rightPanelMode === 'list' ? 'detailed' : 'grid'}
                      />
                    )
                  )}
                  {whyDrawerSku && (
                    <div className={styles.whyDrawer}>
                      <div className={styles.whyDrawerHeader}>
                        <span>Why this product: {whyDrawerSku}</span>
                        <button
                          className={styles.iconBtn}
                          aria-label="Close product explanation"
                          onClick={() => { setWhyDrawerSku(null); setWhyDrawerData(null); setWhyDrawerError(null); }}
                        >×</button>
                      </div>
                      {whyDrawerLoading && <div className={styles.muted}>Loading explanation...</div>}
                      {whyDrawerError && <div className={styles.muted}>{whyDrawerError}</div>}
                      {!whyDrawerLoading && whyDrawerData && (
                        <div className={styles.whyBody}>
                          <ProductWhyEvidence explanation={whyDrawerData} />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Decision Trace Modal */}
      {/* Open the trace on the SOURCING turn's trace when a procurement context exists, so the Procurement
          tab/badge resolves — otherwise a later upsell turn's trace would show no journey. (See lib/trace.) */}
      {traceOpen && <DecisionTrace
        traceId={activeShoppingCase?.case_id
          ? normalizeTraceId(
            ambiguityExploration?.trace_id || activeShoppingCase.case_id.replace(/^sc-/, ''),
          )
          : procurementAwareTraceId(traceId, sourcingTraceId, Boolean(sourcingIntent || fulfilmentCase || bulkAlternatives.length > 0 || sourcingTraceId))}
        onClose={() => setTraceOpen(false)} imageTriage={imageTriageRaw} initialTab={traceInitialTab} evidence={traceEvidence} />}

      {/* Escalation Room Modal */}
      {escalationOpen && escalationIncidentId && (
        <EscalationRoom incidentId={escalationIncidentId} buyerToken={escalationBuyerToken} onClose={() => setEscalationOpen(false)} />
      )}

      {/* Login Modal */}
      {showLogin && (
        <LoginModal
          onClose={() => setShowLogin(false)}
          onLogin={(u) => {
            setStoredAuthIdentity(u.email, u.name);
            setAuthUser({ email: u.email, name: u.name });
            setShowLogin(false);
          }}
        />
      )}

      {/* Admin / Operator Dashboard — rendered for authenticated users */}
      {showAdminDash && authUser && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1100, background: '#fff', overflow: 'auto' }}>
          <button
            style={{ position: 'fixed', top: 12, right: 16, zIndex: 1200, padding: '6px 14px', cursor: 'pointer' }}
            onClick={() => setShowAdminDash(false)}
          >✕ Close</button>
          <AdminDashboard />
        </div>
      )}
    </div>
  );
}
