import { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import styles from './App.module.css';
import ProductGrid from './components/ProductGrid';
import StorefrontEmphasisBanner from './components/StorefrontEmphasisBanner';
import FulfilmentOptions, { type FulfilmentCaseSummary } from './components/FulfilmentOptions';
import SourcingIntentCard from './components/SourcingIntentCard';
import MultiIntentCard from './components/MultiIntentCard';
import BulkAlternatives, { type BulkAlternativeOption } from './components/BulkAlternatives';
import ExternalResearchPanel, { type ExternalResearchItem } from './components/ExternalResearchPanel';
import DecisionTrace from './components/DecisionTrace';
import EscalationRoom from './components/EscalationRoom';
import RightPanelExtras from './components/RightPanelExtras';
import { apiUrl, safeJson, getCart, addCartItem, removeCartItem, setCartItemQty, clearCart, emitConsumerSignal, emitPageView, type SourcingIntent, type MultiIntentPlan } from './lib/api';
import AttachmentButton from './components/AttachmentButton';
import DisambiguationButtons from './components/DisambiguationButtons';
import { useDualSTT } from './hooks/useDualSTT';
import CartPanel from './components/CartPanel';
import LoginModal from './components/LoginModal';
import AdminDashboard from './components/AdminDashboard';
import { productShortLabel } from './lib/productDisplay';
import { csrfHeaders } from './lib/csrf';
import { detectPII } from './lib/pii';
import {
  detectCVIssueType,
  detectPanelMode,
  hasDamageSignal,
  isCartUpsellIntentQuery,
  isComplaintIntent,
  isShoppingIntentQuery,
  shouldRouteToComplaint,
  type RightPanelMode,
} from './lib/queryIntent';
import {
  clearStoredAuthIdentity,
  clearStoredRole,
  clearStoredUid,
  getStoredAuthIdentity,
  getStoredUid,
  setStoredAuthIdentity,
} from './lib/browserSession';

export type Product = {
  sku: string;
  name: string;
  display_name?: string;
  subtitle?: string;
  price: number;
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

type ProductWhyExplanation = {
  sku?: string;
  reason_summary?: string;
  matched_constraints?: string[];
  rank_factors?: any[];
  disqualifiers?: string[];
  alternatives_not_selected?: any[];
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

function formatAUD(n: number): string {
  return n.toLocaleString('en-AU', { style: 'currency', currency: 'AUD', maximumFractionDigits: 0 });
}

// Render a product price honestly: a real amount when we have one (from price OR price_cents), and an
// em-dash when the object carries no price — never a misleading "$0" (demo-truth, same class as the
// $0 budget-band fix).
function formatPrice(p: any): string {
  const v = productPrice(p);
  return v > 0 ? formatAUD(v) : '—';
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
    return `${budgetHint} Top ${useCase} options are ${top.join(' and ')}. Windows picks range from ${formatAUD(minPrice)} to ${formatAUD(maxPrice)}.`;
  }
  if (lane === 'macbook') {
    return `${budgetHint} ${top.join(' and ')} are prioritized for battery life and reliability, from ${formatAUD(minPrice)} to ${formatAUD(maxPrice)}.`;
  }
  return `${budgetHint} Tablet/Chromebook alternatives are shown when portability or price make more sense (${top.join(' and ')}, ${formatAUD(minPrice)}–${formatAUD(maxPrice)}).`;
}


function useProducts() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const ctl = new AbortController();
    fetch('/ui/products.json', { signal: ctl.signal })
      .then((r) => r.json())
      .then((d) => setProducts(Array.isArray(d) ? d : Array.isArray(d?.products) ? d.products : []))
      .catch(() => setProducts([]))
      .finally(() => setLoading(false));
    return () => ctl.abort();
  }, []);
  return { products, loading };
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
  const { products, loading } = useProducts();
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [headerSearchValue, setHeaderSearchValue] = useState('');

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
  const [displayProducts, setDisplayProducts] = useState<Product[]>([]);
  // Safe-internet-search results (separate labeled source; never owned catalog items).
  const [externalResearch, setExternalResearch] = useState<ExternalResearchItem[]>([]);
  const [fulfilmentCase, setFulfilmentCase] = useState<FulfilmentCaseSummary | null>(null);
  const [sourcingIntent, setSourcingIntent] = useState<SourcingIntent | null>(null);
  // The decision trace of the TURN that produced the sourcing preview — pinned so a later turn's trace
  // doesn't advance past it. confirm-cart links the case to THIS trace, so the Decision-Trace procurement
  // badge resolves against the decision that actually opened the journey (not whatever turn is latest).
  const [sourcingTraceId, setSourcingTraceId] = useState<string | null>(null);
  // P0 multi-intent plan (amend chosen qty + scoped new lines) surfaced for buyer confirmation.
  const [multiIntent, setMultiIntent] = useState<MultiIntentPlan | null>(null);
  const [bulkAlternatives, setBulkAlternatives] = useState<BulkAlternativeOption[]>([]);
  const [tierFilter, setTierFilter] = useState<'all' | 'lower' | 'higher'>('all');
  const [traceId, setTraceId] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);
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
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatBodyRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [cvPrefillImages, setCvPrefillImages] = useState<File[]>([]);
  const [cvAutoIssueType, setCvAutoIssueType] = useState<string | undefined>(undefined);
  const [imageTriageContexts, setImageTriageContexts] = useState<any[]>([]);
  const [imageTriageRaw, setImageTriageRaw] = useState<any[]>([]);
  const [visualSearchQuery, setVisualSearchQuery] = useState('');
  const [pendingImageContext, setPendingImageContext] = useState<PendingImageContext | null>(null);
  const [imageRoutingInFlight, setImageRoutingInFlight] = useState(false);
  const [lastCvSecurityNoteKey, setLastCvSecurityNoteKey] = useState<string | null>(null);
  const [whyDrawerSku, setWhyDrawerSku] = useState<string | null>(null);
  const [whyDrawerData, setWhyDrawerData] = useState<ProductWhyExplanation | null>(null);
  const [whyDrawerLoading, setWhyDrawerLoading] = useState(false);
  const [whyDrawerError, setWhyDrawerError] = useState<string | null>(null);
  const uid = (getStoredUid() || 'demo-user');
  // Dev-only debug metadata (LLM tier·model badge) is noise for a pilot buyer — show it only in a dev build
  // or when explicitly opted in (localStorage 'shopsquire_debug'='1'), never to a normal shopper.
  const showDebugBadges = Boolean(
    (import.meta as any)?.env?.DEV ||
    (typeof localStorage !== 'undefined' && localStorage.getItem('shopsquire_debug') === '1'),
  );

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
      },
      source_name: files[idx]?.name || `Image ${idx + 1}`,
      // Propagate damage/repair intent signals so ImageRecommendPanel can gate on them
      intent_routing: (typeof t?.intent_routing === 'object' && t.intent_routing) ? t.intent_routing : null,
      damage_score: typeof t?.damage_score === 'number' ? t.damage_score : null,
    }));
  }, []);

  const makeClientFastImageTriage = useCallback((file: File) => {
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
        clean: !suspiciousName,
        signals: {
          fast_triage_timeout: true,
          filename_suspicious: suspiciousName,
        },
        analysis_stage: 'client_safe_hint',
        verdict: 'Image bytes are queued for background security enrichment; product recommendations use safe filename hints only.',
      },
    };
  }, []);

  const fetchImageTriages = useCallback(async (files: File[], fast = false) => {
    const triagePromises = files.map(async (file) => {
      const fd = new FormData();
      fd.append('image', file);
      const triagePath = fast ? '/api/v1/vision/triage?fast=1' : '/api/v1/vision/triage';
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
        if (!r.ok) return null;
        const data = await safeJson(r);
        if (!data) return null;
        data._filename = file.name;
        return data;
      } catch {
        if (!fast) return null;
        return makeClientFastImageTriage(file);
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
  const stt = useDualSTT();

  // Sync STT transcript into input
  useEffect(() => {
    if (stt.transcript) setInputValue(stt.transcript);
  }, [stt.transcript]);

  /** Add files from AttachmentButton / drop / paste */
  const handleAttach = useCallback((files: File[]) => {
    const imgFiles = files.filter(f => f.type.startsWith('image/'));
    if (imgFiles.length === 0) return;
    setAttachedFiles(prev => [...prev, ...imgFiles]);
    // Generate thumbnails as data URLs
    imgFiles.forEach(f => {
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
    try {
      const j = await addCartItem(uid, sku, Math.max(1, Math.floor(qty)));
      setCart(j);
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
      // honesty: when the confirmed qty exceeds stock, tell the buyer the rest will be sourced.
      const sf = (j as any)?.sourcing_shortfall;
      if ((j as any)?.sourcing_required && sf && Number(sf.shortfall) > 0) {
        const nm = products.find((p) => p.sku === sku)?.name || sku;
        setChatOpen(true);
        setMessages((prev) => [...prev, { role: 'assistant' as const, timestamp: new Date(),
          content: `Set **${nm}** to ${sf.requested}. ${sf.available_now} in stock now — the other ${sf.shortfall} will be sourced from suppliers when you confirm your cart.` }]);
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
      const j = await clearCart(uid);
      setCart(j);
    } catch {
      // ignore
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

  const handleSend = async (opts?: { queryOverride?: string; nqeSelection?: { question_id: string; option_id: string; option_label: string; option_value?: string } }) => {
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
        const useFastImageTriage = !complaintIntent && !explicitComplaintIntent;
        setImageRoutingInFlight(true);
        try {
          imageTriageResults = useFastImageTriage
            ? currentAttachedFiles.map((file) => makeClientFastImageTriage(file))
            : await fetchImageTriages(currentAttachedFiles, false);
        } finally {
          setImageRoutingInFlight(false);
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

          // Let the first recommendation render before starting heavyweight security enrichment.
          window.setTimeout(() => void (async () => {
            try {
              const deepResults = await fetchImageTriages(currentAttachedFiles, false);
              if (!Array.isArray(deepResults) || deepResults.length === 0) return;
              setImageTriageContexts(toImageTriageContexts(deepResults, currentAttachedFiles));
              setImageTriageRaw(deepResults);
            } catch {
              // Keep the fast-path visual route even if deep enrichment fails.
            }
          })(), IMAGE_DEEP_TRIAGE_DELAY_MS);

          // For a pure visual-search request, the panel can own the response.
          // For shopping queries with attached images, continue into /chat/query
          // so the chat bubble summarizes the grounded recommendation instead
          // of punting the buyer to the side panel.
          if (!shoppingIntent && explicitVisualIntent) {
            const imageNames = currentAttachedFiles.map(f => f.name).join(', ');
            setMessages(prev => [...prev, {
              role: 'assistant' as const,
              content: `I checked your images (${imageNames}). Open **Visual Search** on the right to see per-image matches, nearest alternatives, and why each pick fits.`,
              timestamp: new Date(),
            }]);
            setIsThinking(false);
            return;
          }
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
            uid: getStoredUid() || 'demo-user',
            cart_total_cents: 0,
            query: q,
            complaint_intent: true,
          }),
        });
        const data = await safeJson(r);
        if (!r.ok || !data) {
          throw new Error((data && data.detail) ? data.detail : `orchestrate_failed (${r.status})`);
        }
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
        const chatPayload: any = { uid, query: q };
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
            const trustedImageEvidence = t?.provider !== 'client_fast_boundary' && (t?.is_product_photo === true || Boolean(productIdentity));
            return {
              // Do not pass filename-derived fast labels into /chat/query; names like
              // apple-red.jpg can otherwise look like product intent and bias ranking.
              labels: trustedImageEvidence && Array.isArray(t?.labels) ? t.labels : [],
              ocr_text: trustedImageEvidence ? (t?.extracted_text || '') : '',
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

        const apiHeaders = {
          'Content-Type': 'application/json',
          ...csrfHeaders(),
          'x-api-key': ((import.meta as any).env?.VITE_API_KEY || ''),
        };
        const tryStreamChat = async (): Promise<any | null> => {
          const ctl = new AbortController();
          const t = setTimeout(() => ctl.abort(), 3500);
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
            clearTimeout(t);
          }
          if (!resp.ok || !resp.body) return null;
          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          let answerPayload: any = null;
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
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
              if (eventName === 'answer' && parsed) {
                answerPayload = parsed;
              }
              splitIdx = buffer.indexOf('\n\n');
            }
          }
          return answerPayload;
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
          const r = await fetch(apiUrl('/api/v1/chat/query'), {
            method: 'POST',
            credentials: 'include',
            headers: apiHeaders,
            body: JSON.stringify(chatPayload),
          });
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
        const prods = (data.products || []) as Product[];
        setExternalResearch(Array.isArray(data.external_research) ? (data.external_research as ExternalResearchItem[]) : []);
        setFulfilmentCase(data.fulfillment_case && (data.fulfillment_case as any).case_id ? (data.fulfillment_case as FulfilmentCaseSummary) : null);
        // FLUID-procurement preview (FULFILLMENT_DEFER_TO_CART): a buyer-safe sourcing split with no durable
        // case — the buyer confirms it (GATE 1) via SourcingIntentCard to materialize the cases.
        setSourcingIntent(
          data.sourcing_intent && Array.isArray((data.sourcing_intent as any).lines)
            ? (data.sourcing_intent as SourcingIntent) : null);
        // P0 multi-intent: present only on a genuine mixed turn (amend + scoped new lines). Surface it so
        // the buyer confirms the qty change and adds the scoped picks — never silently applied.
        setMultiIntent(
          data.multi_intent && Array.isArray((data.multi_intent as any).plan) && (data.multi_intent as any).plan.length > 0
            ? (data.multi_intent as MultiIntentPlan) : null);
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
        const nextTraceId = normalizeTraceId(data.decision_trace_id || data.trace_id || data.decision_id || data.case_id || null);
        // Pin the sourcing trace to THIS turn only when this turn produced a sourcing preview; otherwise
        // leave the previously-pinned one intact so a later plain query doesn't unlink the confirm.
        if (data.sourcing_intent && Array.isArray((data.sourcing_intent as any).lines) && (data.sourcing_intent as any).lines.length > 0) {
          setSourcingTraceId(nextTraceId);
        }
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
        setTraceId(nextTraceId);

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
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else if (prods.length > 0) {
          const visibleProducts = prods.slice(0, 12);
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
            ...(narrationJobId ? { narrationJobId } : {}),
          };
          setMessages(prev => [...prev, assistantMsg]);
        } else {
          // Zero results: only override panel for explicit support/cart flows.
          // Do NOT switch to 'grid' on zero results — that causes a flicker
          // on follow-up refine queries where the panel was already in a useful state.
          if (panelContract?.mode === 'support') switchRightPanelMode('faq');
          else if (cartUpsellIntent) switchRightPanelMode('cart');
          // else: keep current panel mode unchanged
          const nqePrompt = formatNextQuestions(nextQuestions);
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
            ...(narrationJobId ? { narrationJobId } : {}),
          };
          setMessages(prev => [...prev, assistantMsg]);
        }
        // Async narration: poll the richer LLM prose and replace the tagged message in place. Best-effort
        // — on timeout/error we keep the deterministic grounded answer already shown.
        if (narrationJobId) {
          const _poll = (() => {
            let tries = 0;
            const tick = async () => {
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
                  setMessages(prev => prev.map(m =>
                    m.narrationJobId === narrationJobId
                      ? { ...m, content: polished, narrationJobId: undefined }
                      : m));
                  return;
                }
                if (status === 'error' || tries >= 12) return;  // give up; keep the deterministic answer
              } catch {
                if (tries >= 12) return;
              }
              setTimeout(tick, 1250);  // ~15s total budget
            };
            setTimeout(tick, 1250);
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
      setIsThinking(false);
    }
  };

  const handleQuickAction = (query: string) => {
    setInputValue(query);
    setTimeout(() => handleSend({ queryOverride: query }), 100);
  };

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
              className={styles.searchInput}
              value={headerSearchValue}
              onChange={(e) => setHeaderSearchValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleHeaderSearch(); }}
            />
            <button className={styles.searchBtn} onClick={handleHeaderSearch}>Search</button>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.headerBtn} onClick={() => { refreshCart(); switchRightPanelMode('cart'); }}>
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
        <StorefrontEmphasisBanner />
        <div className={styles.categoryBar}>
          <span className={styles.categoryTitle}>Laptops</span>
          <div className={styles.filters}>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('Show me the best value laptops sorted by price')}>Price</button>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('Show me laptops with 16GB RAM or more')}>RAM</button>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('What laptop brands do you carry?')}>Brand</button>
            <button className={styles.filterBtn} onClick={() => openChatWithQuery('Show me laptops with a dedicated GPU or RTX graphics card')}>GPU</button>
          </div>
        </div>
        <ProductGrid products={displayProducts.length > 0 ? filteredDisplayProducts : products} onAdd={addToCart} viewMode="grid" />
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
                  <span className={styles.chatTitle}>ShopSquire Assistant</span>
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
                                {para.trim()}
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
                      {msg.nextQuestions && msg.nextQuestions.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                          {/* cap at 2 so the turn asks focused questions, not a wall (was 3-4 + duplicated below) */}
                          {msg.nextQuestions.slice(0, 2).map((nq) => (
                            <div key={nq.id} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, width: '100%' }}>
                              {nq.why_hint && (
                                <button type="button" className={styles.hintBtn} title={nq.why_hint}>
                                  Why this question?
                                </button>
                              )}
                              <button
                                type="button"
                                className={styles.filterBtn}
                                onClick={() => handleQuickAction(nq.text)}
                              >
                                {nq.text}
                              </button>
                              {Array.isArray(nq.options) && nq.options.length > 0 && (
                                <>
                                  {nq.options.map((opt) => (
                                    <button
                                      key={`${nq.id}:${opt.id}`}
                                      type="button"
                                      className={styles.filterBtn}
                                      onClick={() => handleNqeOptionSelect(nq, opt)}
                                    >
                                      {opt.label}
                                    </button>
                                  ))}
                                </>
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
                  </div>
                ))}
                {(isThinking || imageRoutingInFlight) && (
                  <div className={`${styles.message} ${styles.assistant}`}>
                    <div className={`${styles.messageContent} ${styles.thinkingBubble}`}>
                      <span className={styles.thinkingDot}>.</span>
                      <span className={styles.thinkingDot}>.</span>
                      <span className={styles.thinkingDot}>.</span>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Composer Card */}
              <div className={styles.chatFooter}>
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
                <div className={styles.composerRow}>
                  <AttachmentButton onFiles={handleAttach} className={styles.inputIconBtn} />
                  <textarea
                    ref={textareaRef}
                    className={styles.chatInput}
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
                  >
                    <MicIcon />
                    {stt.whisperPending && <span className={styles.whisperDot} />}
                  </button>
                  <button className={styles.sendBtn} onClick={() => handleSend()} disabled={isThinking || imageRoutingInFlight}><SendIcon /></button>
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
                        onAmendQty={(sku, qty) => setCartQty(sku, qty, true)}
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
                    <RightPanelExtras mode="visual_search" initialImageContexts={imageTriageContexts} userQuery={visualSearchQuery} onTraceId={(tid) => setTraceId(normalizeTraceId(tid))} onClarify={(q) => { if (isThinking) return; setInputValue(q); handleSend({ queryOverride: q }); }} onAdd={addToCart} />
                  ) : rightPanelMode === 'image_context' ? (
                    <RightPanelExtras mode="image_context" initialImageContexts={imageTriageContexts} userQuery={visualSearchQuery} onTraceId={(tid) => setTraceId(normalizeTraceId(tid))} onClarify={(q) => { if (isThinking) return; setInputValue(q); handleSend({ queryOverride: q }); }} onAdd={addToCart} />
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
                    rightPanelMode === 'cart' ? (
                      <CartPanel
                        uid={uid}
                        cart={cart}
                        onRefresh={refreshCart}
                        onRemove={removeFromCart}
                        onClear={clearCartAll}
                        onAdd={addToCart}
                        onSetQty={setCartQty}
                        onTraceId={(tid) => setTraceId(normalizeTraceId(tid))}
                      />
                    ) : filteredDisplayProducts.length === 0 && ['grid', 'list', 'compare'].includes(rightPanelMode) ? (
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
                        <button className={styles.iconBtn} onClick={() => { setWhyDrawerSku(null); setWhyDrawerData(null); setWhyDrawerError(null); }}>×</button>
                      </div>
                      {whyDrawerLoading && <div className={styles.muted}>Loading explanation...</div>}
                      {whyDrawerError && <div className={styles.muted}>{whyDrawerError}</div>}
                      {!whyDrawerLoading && whyDrawerData && (
                        <div className={styles.whyBody}>
                          <div><strong>Matched constraints:</strong> {(whyDrawerData.matched_constraints || []).join(', ') || '--'}</div>
                          <div><strong>Rank factors:</strong> {Array.isArray(whyDrawerData.rank_factors) ? whyDrawerData.rank_factors.length : 0}</div>
                          <div><strong>Disqualifiers:</strong> {(whyDrawerData.disqualifiers || []).join(', ') || '--'}</div>
                          <div><strong>Alternatives not selected:</strong> {Array.isArray(whyDrawerData.alternatives_not_selected) ? whyDrawerData.alternatives_not_selected.length : 0}</div>
                          <div><strong>Summary:</strong> {whyDrawerData.reason_summary || '--'}</div>
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
      {/* When a procurement context exists, open the trace on the SOURCING turn's trace so the Procurement
          tab/badge resolves — otherwise a later upsell turn's trace would show no journey. */}
      {traceOpen && <DecisionTrace
        traceId={(sourcingIntent || fulfilmentCase || bulkAlternatives.length > 0) ? (sourcingTraceId || traceId) : traceId}
        onClose={() => setTraceOpen(false)} imageTriage={imageTriageRaw} />}

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
