import { useEffect, useState, useCallback, useRef } from 'react';
import { productDisplayName, productSubtitle } from '../lib/productDisplay';
import styles from './ImageRecommendPanel.module.css';

/* ---------- types ---------- */
export interface ImageAnalysisContext {
  labels: string[];
  ocr_text: string;
  cv_signals: {
    qr_code_detected?: boolean;
    qr_prompt_injection?: boolean;
    manipulation_detected?: boolean;
    qr_external_url_detected?: boolean;
    steg_suspicious?: boolean;
    [key: string]: any;
  };
  /** Optional filename or source identifier shown in the group header */
  source_name?: string;
  /** Intent classification from image_intent_router (cv_triage / visual_search / faq) */
  intent_routing?: { intent?: string; confidence?: number; reason?: string } | null;
  /** Damage score from vision triage (0–1) */
  damage_score?: number | null;
}

interface ProductCard {
  sku: string;
  name: string;
  display_name?: string;
  subtitle?: string;
  price: number;
  specs_summary?: string;
  use_case_fit?: string;
  image_url?: string;
  reasons?: string[];
  why?: string[];
  reason_codes?: any[];
}

interface ImageGroup {
  /** Which image / query spawned this group */
  source: string;
  icon: string;
  trustLevel: TrustLevel;
  friendlyBrand: string;
  securityNote: string;
  analysisState?: 'complete' | 'pending' | 'degraded';
  products: ProductCard[];
  summary: string;
  /** Budget widen state */
  widenState?: { budgetMin: number; budgetMax: number; noResults: boolean; nearestPrice?: number };
  /** Preserve image context per group so widen/nearest stay image-aware. */
  context?: ImageAnalysisContext | null;
  offDomain?: boolean;
  lowSupport?: boolean;
  domainBadge?: string | null;
  fillBadge?: string | null;
  /** One-line "why this fired" for the analyst header */
  detectionReason?: string | null;
  verdictLabel?: string | null;
  confidenceBand?: string | null;
  fastPathTimeout?: boolean;
  tracePayload?: RecommendTracePayload | null;
  /** True when the image was classified as a damaged device — show repair card instead of products */
  isRepairIntent?: boolean;
  repairContext?: { brand: string; damage_score: number } | null;
}

/** Proof-of-purchase uploads (receipt / order / serial) belong ONLY in
 * ownership-proof flows — warranty, repair, return, refund, fraud review — not
 * during normal shopping / visual search, where they are irrelevant and add
 * friction. Gate the CTAs on a proof-relevant intent or query. */
const PROOF_INTENT_RE = /\b(warrant|repair|return|refund|exchange|rma|proof of purchase|receipt|serial|owner|ownership|stolen|fraud|claim|guarantee)\b/i;
export function isProofRelevant(group: ImageGroup, userQuery: string): boolean {
  if (group.isRepairIntent) return true;
  const intent = String(group.context?.intent_routing?.intent || '').toLowerCase();
  if (/(repair|warrant|return|refund|fraud|proof|ownership|claim)/.test(intent)) return true;
  return PROOF_INTENT_RE.test(String(userQuery || ''));
}

type RecommendTracePayload = {
  trace_id?: string | null;
  decision_trace_id?: string | null;
  decision_id?: string | null;
  right_panel?: any;
  security_matrix?: any;
  safe_image_hints?: any;
  ranked_products?: any[];
  image_security?: any;
};

type SuggestResult = {
  products: ProductCard[];
  summary: string;
  nextQuestions: any[];
  traceId: string | null;
  offDomain: boolean;
  lowSupport: boolean;
  domainBadge: string | null;
  fillBadge: string | null;
  linkedArtifactSummary?: string | null;
  linkedArtifactPolicyAction?: string | null;
  linkedArtifactVerdictLabel?: string | null;
  linkedArtifactConfidenceBand?: string | null;
  rightPanel?: any;
  securityMatrix?: any;
  safeImageHints?: any;
  rankedProducts?: any[];
  imageSecurity?: any;
  raw?: RecommendTracePayload;
};

type TrustLevel = 'green' | 'yellow' | 'orange' | 'red';

export interface Props {
  /** Array of image analysis contexts — one per uploaded image */
  imageContexts: ImageAnalysisContext[];
  userQuery: string;
  traceId?: string | null;
  sessionSuspiciousCount?: number;
  /** Callback when user picks a clarifying-question button */
  onClarify?: (question: string) => void;
  /** Callback to propagate the first seen trace_id to the parent */
  onTraceId?: (traceId: string | null) => void;
  /** Add-to-cart callback from App */
  onAdd?: (sku: string) => void;
  /** Canonical products returned by the chat/recommendation turn. When supplied, this component
   * is renderer-only and must not issue its historical independent /suggest request. null means
   * the shared turn is still pending; [] is a completed honest no-match. */
  canonicalProducts?: ProductCard[] | null;
  canonicalSummary?: string;
  /** Temporary rollback switch. Production callers must use the canonical shared turn. */
}

/* ---------- constants ---------- */
const WIDEN_STEPS = [200, 400];


function persistOperatorMetrics(timing: any, traceId: string | null, source = 'visual_search') {
  if (!timing || typeof timing !== 'object') return;
  try {
    const prevRaw = localStorage.getItem('shopsquire_operator_metrics');
    const prev = prevRaw ? JSON.parse(prevRaw) : {};
    localStorage.setItem('shopsquire_operator_metrics', JSON.stringify({
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
      traceId,
      source,
      recordedAt: new Date().toISOString(),
    }));
  } catch {}
}

/* ---------- helpers ---------- */
export function computeTrustLevel(signals: ImageAnalysisContext['cv_signals'], sessionSuspicious: number): TrustLevel {
  const s = signals as Record<string, any>;
  if (sessionSuspicious >= 3 || signals.qr_prompt_injection) return 'red';
  // Explicit threat-hypothesis signals always warrant orange
  if (s.ransomware_indicator || s.c2_beacon_detected || s.payment_social_engineering) return 'orange';
  if (signals.qr_external_url_detected) return 'orange';
  if (sessionSuspicious >= 2 || signals.manipulation_detected || signals.steg_suspicious) return 'orange';
  if (signals.qr_code_detected) return 'yellow';
  return 'green';
}

export function shouldUseFastPath(query: string): boolean {
  const q = String(query || '').toLowerCase();
  if (!q.trim()) return true;
  const hasBudgetSignal = /\$\s*\d{3,5}|\b\d{3,5}\b|\bbudget\b|\bunder\b|\baround\b|\bup to\b/.test(q);
  const wantsReasoning = /\benough\b|\bgo higher\b|\bworth it\b|\bbetter value\b|\boverkill\b|\bwhy\b|\brecommend(?:ed)?\b/.test(q);
  return !(hasBudgetSignal && wantsReasoning);
}

/** One-line analyst explanation for why this image lane was flagged. */
function buildLaneDetectionReason(signals: ImageAnalysisContext['cv_signals']): string {
  const s = signals as Record<string, any>;
  if (signals.qr_prompt_injection) return 'Detected because QR payload is an injection attempt targeting the AI assistant.';
  if (s.ransomware_indicator) return 'Detected because decoded payload references ransomware extension/locking patterns.';
  if (s.payment_social_engineering) return 'Detected because QR payload is an external payment/social-engineering link.';
  if (signals.steg_suspicious) return 'Detected because hidden payload found via steganographic anomaly in pixel data.';
  if (signals.qr_external_url_detected) return 'Detected because QR payload redirects to an external unverified URL.';
  if (signals.adversarial_detected) return 'Detected because adversarial perturbations found targeting the CV model.';
  if (signals.manipulation_detected) return 'Detected because pixel-level manipulation detected; image integrity compromised.';
  return 'Suspicious signals detected in uploaded image.';
}

function buildBuyerSecurityNotice(signals: ImageAnalysisContext['cv_signals']): string {
  const s = signals as Record<string, any>;
  if (s.fast_triage_timeout || s.analysis_pending) {
    return 'Image security enrichment is still running. Recommendations use bounded visual hints until analysis completes.';
  }
  if (s.analysis_degraded) {
    return 'Image analysis is degraded. Recommendations use only the verified evidence available.';
  }
  if (signals.qr_code_detected && s.qr_benign_detected) {
    return 'QR detected and decoded successfully. The visible content looks benign, so recommendations can continue.';
  }
  if (s.payment_social_engineering || signals.qr_external_url_detected || signals.qr_code_detected) {
    return 'Suspicious QR-linked document detected. Admin notified. Recommendations remain available while this image is under review.';
  }
  if (s.c2_beacon_detected) {
    return 'Suspicious hidden payload indicators detected. Admin notified. Recommendations remain available while this image is under review.';
  }
  if (signals.steg_suspicious) {
    return 'Suspicious steganographic payload indicators detected. Admin notified. Recommendations remain available while this image is under review.';
  }
  if (signals.adversarial_detected || signals.manipulation_detected) {
    return 'Image integrity warning detected. Admin notified. Recommendations remain available while this image is under review.';
  }
  return 'Suspicious signals detected. Admin notified. Recommendations remain available while this image is under review.';
}

function buildSafeFallbackQuery(query: string, brandLabel: string): string {
  const cleanBase = stripBudgetHints(query);
  const useCase = inferSummaryUseCase(query);
  if (useCase === 'gaming') return `${cleanBase} gaming laptop show nearest safe in-stock options`.trim();
  if (isWindowsLikeBrand(brandLabel)) return `${cleanBase} windows laptop show nearest in-stock options`.trim();
  if (isAppleLikeBrand(brandLabel)) return `${cleanBase} macbook show nearest in-stock options`.trim();
  return `${cleanBase} laptop show nearest in-stock options`.trim();
}

const TRUST_LABELS: Record<TrustLevel, string> = {
  green: 'Benign',
  yellow: 'Monitoring',
  orange: 'Under Review',
  red: 'Escalated',
};

function groupStatusLabel(group: ImageGroup): string {
  if (group.analysisState === 'pending') return 'Analysis pending';
  if (group.analysisState === 'degraded') return 'Analysis degraded';
  return TRUST_LABELS[group.trustLevel];
}

const TRUST_NOTES: Record<TrustLevel, string> = {
  green: 'Image scanned — no issues found.',
  yellow: 'QR code detected but content appears benign.',
  orange: 'Suspicious signals detected — an admin has been notified.',
  red: 'Multiple security signals — recommendations paused for safety.',
};

/** Convert raw CV labels to a friendly brand / product name for the buyer. */
function friendlyBrand(labels: string[], ocrText: string, sourceName?: string, userQuery?: string): string {
  const lbl = labels.map(l => String(l || '').toLowerCase());
  const ocr = String(ocrText || '').toLowerCase();
  const src = String(sourceName || '').toLowerCase();
  const q = String(userQuery || '').toLowerCase();
  const joined = [...lbl, ocr, src, q].join(' ');
  const hasDeviceHint = /laptop|notebook|computer|pc|macbook|chromebook|copilot|intel|amd|ryzen|ssd|ram|gpu/.test(joined);
  const likelyFruit = /fruit|apple[-_\s]?red|red apple|granny smith|gala apple/.test(joined);
  if (likelyFruit && !hasDeviceHint) return 'Product';
  if (/macbook|apple.*mac/i.test(joined)) return 'MacBook';
  if (/mac|apple/i.test(joined)) return 'Apple';
  if (/lenovo|ideapad|thinkpad|legion|yoga/i.test(joined)) return 'Lenovo';
  if (/dell|xps|inspiron|latitude|alienware/i.test(joined)) return 'Dell';
  if (/hp |hewlett|pavilion|envy|omen|spectre|victus/i.test(joined)) return 'HP';
  if (/asus|rog|zenbook|vivobook|tuf/i.test(joined)) return 'ASUS';
  if (/acer|nitro|predator|swift/i.test(joined)) return 'Acer';
  if (/msi|katana|raider|stealth/i.test(joined)) return 'MSI';
  if (/samsung|galaxy\s*book/i.test(joined)) return 'Samsung';
  if (/chromebook/i.test(joined)) return 'Chromebook';
  if (/laptop|notebook|computer/i.test(joined)) return 'Laptop';
  return 'Product';
}

/** Detect use-case from query for clarifying questions. */
function detectUseCase(query: string): string | null {
  const q = query.toLowerCase();
  if (/highschool|high school|yr\s?(?:7|8|9|10|11|12)|year\s?(?:7|8|9|10|11|12)|teen/i.test(q)) return 'school';
  if (/universit|uni\b|college|student|lecture|study/i.test(q)) return 'university';
  if (/gaming|game|fps|rtx|gpu/i.test(q)) return 'gaming';
  if (/cod(e|ing)|develop|program/i.test(q)) return 'coding';
  if (/content|creat|video|edit|design|photo/i.test(q)) return 'content_creation';
  if (/office|admin|work|excel|zoom|teams|meet/i.test(q)) return 'office';
  return null;
}

/** Default budget ceiling (AUD cents * 100 → display dollars) for a given use-case. */
const USE_CASE_BUDGET: Record<string, number> = {
  school: 1100,
  university: 1200,
  coding: 1500,
  gaming: 2000,
  content_creation: 1800,
  office: 900,
};

/** Derive a short pros note from product specs + price. */
export function buildProsNote(p: ProductCard, userQuery: string): string {
  const pros: string[] = [];
  const q = userQuery.toLowerCase();
  const specs = p.specs_summary || '';
  if (/\b16\s*gb/i.test(specs)) pros.push('16 GB RAM');
  else if (/\b8\s*gb/i.test(specs)) pros.push('8 GB RAM');
  if (/1\s*tb/i.test(specs)) pros.push('1 TB storage');
  else if (/512/i.test(specs)) pros.push('512 GB SSD');
  if (/oled/i.test(p.name)) pros.push('OLED display');
  if (/touch/i.test(p.name)) pros.push('Touchscreen');
  if (/\b(?:rtx|gtx)\s*\d|\bradeon\s+(?:rx|pro)\b|\bintel\s+arc\s+[ab]\d/i.test(specs)) {
    pros.push('Discrete GPU');
  }
  if (/universit|student/i.test(q) && p.price < 1000) pros.push('Student-budget friendly');
  if (/gaming/i.test(q) && /rtx/i.test(specs)) pros.push('Gaming-ready GPU');
  return pros.slice(0, 3).join(' · ');
}

/** Clarifying questions based on detected use-case */
const CLARIFYING_QUESTIONS: Record<string, { prompt: string; options: string[] }> = {
  school: {
    prompt: 'What will your son mainly use it for at school?',
    options: ['Classwork & homework', 'Coding & projects', 'Creative assignments', 'Light gaming', 'General school use'],
  },
  university: {
    prompt: 'What will you mainly use it for at uni?',
    options: ['Note-taking & lectures', 'Coding & development', 'Content creation', 'Light gaming', 'General uni work'],
  },
  office: {
    prompt: 'What kind of office work?',
    options: ['Emails & documents', 'Video calls & meetings', 'Data / spreadsheets', 'Coding / dev work', 'Video rendering / design'],
  },
  general: {
    prompt: 'What will you mainly use this for?',
    options: ['University / study', 'Gaming', 'Office / work', 'Content creation', 'General browsing'],
  },
};

function formatPrice(dollars: number): string {
  if (!(dollars > 0)) return 'Price on request';
  return `$${dollars.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function stripBudgetHints(query: string): string {
  return String(query || '')
    .replace(/\$\s*\d{3,5}\s*(?:to|-)\s*\$?\s*\d{3,5}/gi, ' ')
    .replace(/\bbetween\s+\$?\d{3,5}\s+and\s+\$?\d{3,5}\b/gi, ' ')
    .replace(/\bunder\s+\$?\d{2,5}\b/gi, ' ')
    .replace(/\bover\s+\$?\d{2,5}\b/gi, ' ')
    .replace(/\bbudget\s+\$?\d{2,5}\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractBudgetMax(query: string, fallbackMax?: number): number | undefined {
  const q = String(query || '');
  const range = q.match(/\b(\d{3,5})\s*(?:to|-)\s*(\d{3,5})\b/i);
  if (range) {
    const a = Number(range[1]);
    const b = Number(range[2]);
    if (Number.isFinite(a) && Number.isFinite(b)) return Math.max(a, b);
  }
  const under = q.match(/\bunder\s+\$?\s*(\d{2,5})\b/i);
  if (under) {
    const v = Number(under[1]);
    if (Number.isFinite(v)) return v;
  }
  const enough = q.match(/\b(?:is|around|about|budget|max(?:imum)?|up to)?\s*\$?\s*(\d{3,5})\s*(?:enough|budget|max(?:imum)?|cap)?\b/i);
  if (enough) {
    const v = Number(enough[1]);
    if (Number.isFinite(v)) return v;
  }
  const allNums = (q.match(/\b\d{3,5}\b/g) || [])
    .map((n) => Number(n))
    .filter((n) => Number.isFinite(n));
  if (allNums.length > 0) {
    const v = Math.max(...allNums);
    if (v >= 300 && v <= 10000) return v;
  }
  return fallbackMax;
}

/** Extract the lower bound from range queries like "from 1500 to 2200" or "$1500-$2200". */
function extractBudgetMin(query: string): number | undefined {
  const q = String(query || '');
  // "from X to Y", "X to Y", "X-Y", "$X-$Y", "between X and Y"
  const range = q.match(/\b(?:from\s+)?\$?\s*(\d{3,5})\s*(?:to|-)\s*\$?\s*(\d{3,5})\b/i);
  if (range) {
    const a = Number(range[1]);
    const b = Number(range[2]);
    if (Number.isFinite(a) && Number.isFinite(b)) return Math.min(a, b);
  }
  const between = q.match(/\bbetween\s+\$?\s*(\d{3,5})\s+and\s+\$?\s*(\d{3,5})\b/i);
  if (between) {
    const a = Number(between[1]);
    const b = Number(between[2]);
    if (Number.isFinite(a) && Number.isFinite(b)) return Math.min(a, b);
  }
  const over = q.match(/\bover\s+\$?\s*(\d{3,5})\b/i);
  if (over) {
    const v = Number(over[1]);
    if (Number.isFinite(v)) return v;
  }
  return undefined;
}

function sanitizeSummary(summary: string, productCount: number, fallback: string): string {
  const msg = String(summary || '').trim();
  if (productCount <= 0) return 'No products found in your budget range.';
  if (!msg) return fallback;
  return msg;
}

function isAppleLikeBrand(label: string): boolean {
  const v = String(label || '').toLowerCase();
  return v.includes('macbook') || v.includes('apple');
}

function isWindowsLikeBrand(label: string): boolean {
  const v = String(label || '').toLowerCase();
  return ['lenovo', 'dell', 'hp', 'asus', 'acer', 'msi', 'samsung', 'microsoft', 'surface', 'windows'].some((b) => v.includes(b));
}

function assistantClaimsProducts(text: string | null | undefined): boolean {
  return /top picks|i['’]ve found \d+|found \d+ (?:matches|products|options)/i.test(String(text || ''));
}

export function normalizeUseCaseFit(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;
  if (!value || typeof value !== 'object') return null;
  const fit = value as Record<string, unknown>;
  const useCase = String(fit.use_case || '').trim().replace(/_/g, ' ');
  const explicitVerdict = String(fit.verdict || '').trim().replace(/_/g, ' ');
  const suitable = typeof fit.suitable === 'boolean' ? fit.suitable : null;
  const prefix = explicitVerdict
    || (suitable === true ? `Suitable${useCase ? ` for ${useCase}` : ''}` : '')
    || (suitable === false ? `Not suitable${useCase ? ` for ${useCase}` : ''}` : '');
  const details = suitable === false ? fit.gaps : fit.strengths;
  const firstDetail = Array.isArray(details) ? String(details[0] || '').trim().replace(/_/g, ' ') : '';
  return [prefix, firstDetail].filter(Boolean).join(' - ') || null;
}

function normalizeProductCard(raw: any): ProductCard | null {
  if (!raw || typeof raw !== 'object') return null;
  const sku = String(raw.sku || raw.id || '').trim();
  const name = String(raw.name || raw.title || '').trim();
  if (!sku && !name) return null;
  const price =
    typeof raw.price_cents === 'number' && raw.price_cents > 0
      ? raw.price_cents / 100
      : typeof raw.price === 'number'
        ? raw.price
        : typeof raw.price_dollars === 'number'
          ? raw.price_dollars
          : 0;
  const specsSummary =
    raw.specs_summary
    || [raw.specs?.cpu, raw.specs?.ram_gb ? `${raw.specs.ram_gb}GB` : null, raw.specs?.gpu]
      .filter(Boolean)
      .join(' \u00B7 ');
  return {
    sku,
    name: name || sku || 'Unknown',
    display_name: raw.display_name || raw.specs?.display_name || undefined,
    subtitle: raw.subtitle || raw.specs?.subtitle || undefined,
    price,
    specs_summary: specsSummary || undefined,
    use_case_fit: normalizeUseCaseFit(raw.use_case_suitability || raw.use_case_fit || raw.reason) || undefined,
    image_url: raw.image_url || null,
    reasons: Array.isArray(raw.reasons) ? raw.reasons.slice(0, 5).map(String) : undefined,
    reason_codes: Array.isArray(raw.reason_codes) ? raw.reason_codes.slice(0, 5) : undefined,
  };
}

function parseProducts(data: any): ProductCard[] {
  const raw: any[] = [];
  if (Array.isArray(data?.results)) raw.push(...data.results);
  if (Array.isArray(data?.products)) raw.push(...data.products);
  const rightPanel = data?.right_panel;
  if (rightPanel && typeof rightPanel === 'object') {
    if (Array.isArray(rightPanel?.lower_tier?.items)) raw.push(...rightPanel.lower_tier.items);
    if (Array.isArray(rightPanel?.higher_tier?.items)) raw.push(...rightPanel.higher_tier.items);
    if (Array.isArray(rightPanel?.anchor_sections)) {
      for (const section of rightPanel.anchor_sections) {
        if (Array.isArray(section?.top_products)) raw.push(...section.top_products);
      }
    }
  }
  const seen = new Set<string>();
  const out: ProductCard[] = [];
  for (const item of raw) {
    const card = normalizeProductCard(item);
    if (!card) continue;
    const key = card.sku || card.name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(card);
  }
  return out;
}

function buildNearestLabel(brandLabel: string): string {
  const brand = String(brandLabel || '').trim();
  if (!brand) return 'Show nearest';
  if (/^macbook$/i.test(brand)) return 'Show nearest MacBook';
  return `Show nearest ${brand}`;
}

function buildNearestQuery(query: string, brandLabel: string): string {
  const clean = stripBudgetHints(query);
  const brand = String(brandLabel || '').trim();
  const needsDeviceHint = !/\blaptop|notebook|computer|pc|macbook|chromebook\b/i.test(clean);
  if (!brand) return `${clean} show nearest in-stock options`.trim();
  if (/^macbook$/i.test(brand)) return `${clean} ${needsDeviceHint ? 'laptop ' : ''}apple macbook show nearest in-stock options`.trim();
  return `${clean} ${needsDeviceHint ? 'laptop ' : ''}${brand} show nearest in-stock options`.trim();
}

function buildNoResultsText(brandLabel: string): string {
  const brand = String(brandLabel || '').trim();
  if (!brand) return 'No in-stock products fit this budget right now.';
  if (/^product$/i.test(brand)) return 'This image appears outside this laptop catalog. Upload a device photo or use a text query.';
  if (/^macbook$/i.test(brand)) return 'No in-stock MacBook products fit this budget right now.';
  return `No in-stock ${brand} products fit this budget right now.`;
}

function inferSummaryUseCase(query: string): 'study' | 'gaming' | 'work' | 'daily use' {
  const q = String(query || '').toLowerCase();
  if (/highschool|high school|yr\s?(?:7|8|9|10|11|12)|year\s?(?:7|8|9|10|11|12)|teen|student|university|uni|college/i.test(q)) return 'study';
  if (/gaming|fps|gpu|rtx|render|creative|video editing/i.test(q)) return 'gaming';
  if (/work|office|meeting|excel|corporate|business/i.test(q)) return 'work';
  return 'daily use';
}

function _prettyReason(reason: string): string {
  const r = String(reason || '').trim();
  if (!r) return '';
  if (/^\+?embedding_similarity$/i.test(r)) return 'close visual/spec match';
  if (/^\+?cross_encoder$/i.test(r)) return 'strong text-to-product match';
  if (/^\+?in_stock$/i.test(r)) return 'in stock';
  if (/^\+?use_case_match/i.test(r)) return 'fits your use case';
  return r.replace(/^[+-]/, '').replace(/_/g, ' ');
}

function naturalSummary(rawSummary: string, products: ProductCard[], query: string, brand: string): string {
  const raw = String(rawSummary || '').trim();
  if (products.length === 0) {
    if (raw && /timed out|could not load/i.test(raw)) return raw;
    if (raw && /catalog|unrelated products|does not match this merchant/i.test(raw)) return raw;
    return buildNoResultsText(brand);
  }
  const useCase = inferSummaryUseCase(query);
  const top = products.slice(0, 2).map((p) => {
    const title = productDisplayName(p);
    const why = buildProsNote(p, query) || _prettyReason(p.use_case_fit || '');
    return why ? `${title} (${why})` : title;
  });
  const r = raw.replace(/\(\s*[+-]?[a-z_]+(?:\s*,\s*[+-]?[a-z_]+)*\s*\)/gi, '').trim();
  if (r && r.length < 180) return r;
  return `Best ${useCase} picks here are ${top.join(' and ')}.`;
}

function lockedOffDomainSummary(query: string): string {
  const useCase = inferSummaryUseCase(query);
  const q = String(query || '').toLowerCase();
  const likelyApple = /apple/.test(q);
  const hint =
    useCase === 'work'
      ? 'Upload a work laptop or electronics photo, or use a text query.'
      : useCase === 'study'
        ? 'Upload a study laptop or device photo, or use a text query.'
        : 'Upload a device photo from this store category, or use a text query.';
  const prefix = likelyApple
    ? 'The uploaded image looks like fruit or a non-device product, not a laptop.'
    : 'This image appears outside the current merchant catalog.';
  return `${prefix} I did not substitute unrelated products. ${hint}`;
}

function looksOffDomainContext(ctx: ImageAnalysisContext | null, brandLabel: string): boolean {
  const brand = String(brandLabel || '').trim().toLowerCase();
  if (brand === 'product') return true;
  const joined = `${ctx?.source_name || ''} ${(ctx?.labels || []).join(' ')} ${ctx?.ocr_text || ''}`.toLowerCase();
  return /fruit|apple[-_\s]?red|red apple|banana|lettuce|fresh produce|grocery/.test(joined) && !/laptop|notebook|computer|macbook|chromebook|intel|amd|ryzen/.test(joined);
}

function looksLikelyDeviceContext(ctx: ImageAnalysisContext | null, brandLabel: string): boolean {
  const joined = `${brandLabel || ''} ${ctx?.source_name || ''} ${(ctx?.labels || []).join(' ')} ${ctx?.ocr_text || ''}`.toLowerCase();
  const strongDeviceSignals = /laptop|notebook|computer|pc|macbook|chromebook|dell|lenovo|hp|asus|acer|msi|samsung|surface|intel|amd|ryzen|ssd|ram|gpu/.test(joined);
  const produceSignals = /fruit|apple[-_\s]?red|red apple|banana|lettuce|fresh produce|grocery/.test(joined);
  return strongDeviceSignals && !produceSignals;
}

function conciseLaneReason(products: ProductCard[], query: string, brand: string): string {
  if (!products.length) return buildNoResultsText(brand);
  const useCase = inferSummaryUseCase(query);
  const top = products[0];
  const title = productDisplayName(top);
  const subtitle = productSubtitle(top);
  if (useCase === 'work') {
    return `${title}${subtitle ? ` • ${subtitle}` : ''} is a sensible work pick with enough memory and storage for everyday office tasks.`;
  }
  if (useCase === 'study') {
    return `${title}${subtitle ? ` • ${subtitle}` : ''} fits study use with practical specs for classes, homework, and browser-heavy work.`;
  }
  if (useCase === 'gaming') {
    return `${title}${subtitle ? ` • ${subtitle}` : ''} is one of the stronger gaming matches from the uploaded device image.`;
  }
  return `${title}${subtitle ? ` • ${subtitle}` : ''} is the closest in-catalog match for this uploaded image.`;
}

/* ---------- component ---------- */
export default function ImageRecommendPanel({ imageContexts, userQuery, traceId, sessionSuspiciousCount = 0, onClarify, onTraceId, onAdd, canonicalProducts, canonicalSummary }: Props) {
  const [groups, setGroups] = useState<ImageGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarifyQuestions, setClarifyQuestions] = useState<{ prompt: string; options: string[] } | null>(null);
  const [globalRedBlock, setGlobalRedBlock] = useState(false);
  const buildSeqRef = useRef(0);
  const lastBuildKeyRef = useRef('');

  const buildGroups = useCallback(async () => {
    if (canonicalProducts !== undefined) {
      const buildSeq = ++buildSeqRef.current;
      setError(null);
      setGlobalRedBlock(false);
      if (canonicalProducts === null) {
        setGroups([]);
        setLoading(true);
        return;
      }
      const ctx = imageContexts[0] || null;
      const trust = computeTrustLevel(ctx?.cv_signals || {}, sessionSuspiciousCount);
      const signals = (ctx?.cv_signals || {}) as Record<string, any>;
      const analysisState: ImageGroup['analysisState'] = signals.fast_triage_timeout || signals.analysis_pending
        ? 'pending'
        : signals.analysis_degraded ? 'degraded' : 'complete';
      const brand = ctx ? friendlyBrand(ctx.labels, ctx.ocr_text, ctx.source_name, userQuery) : 'Product';
      const canonicalGroup: ImageGroup = {
        source: ctx?.source_name || 'Uploaded image',
        icon: '\uD83D\uDCF8',
        trustLevel: trust,
        friendlyBrand: brand,
        securityNote: trust === 'green' ? TRUST_NOTES.green : buildBuyerSecurityNotice(signals),
        analysisState,
        products: canonicalProducts.slice(0, 10).map(product => ({
          ...product,
          reasons: product.reasons || product.why || [],
        })),
        summary: canonicalSummary || (canonicalProducts.length > 0
          ? 'Matches from the shared recommendation turn.'
          : 'No eligible catalog match was found for the current image, query, and constraints.'),
        context: ctx,
      };
      if (buildSeq === buildSeqRef.current) {
        setGroups([canonicalGroup]);
        setLoading(false);
        setClarifyQuestions(null);
        if (traceId) onTraceId?.(traceId);
      }
      return;
    }
    {
      ++buildSeqRef.current;
      setGroups([]);
      setLoading(false);
      setGlobalRedBlock(false);
      setError('Image recommendation is unavailable for this turn.');
      return;
    }
  }, [canonicalProducts, canonicalSummary, imageContexts, userQuery, sessionSuspiciousCount,
      onTraceId, traceId]);

  const handleWiden = useCallback(async (groupIdx: number, widenAmount: number) => {
    const group = groups[groupIdx];
    if (!group?.widenState || group.offDomain) return;
    const newMax = (group.widenState.budgetMax || 1500) + widenAmount;
    {
      onClarify?.(`${stripBudgetHints(userQuery)} increase the maximum budget to $${newMax}`.trim());
      return;
    }
  }, [groups, userQuery, onClarify, onTraceId]);

  const handleShowNearest = useCallback(async (groupIdx: number) => {
    const group = groups[groupIdx];
    if (!group || group.offDomain) return;
    {
      onClarify?.(buildNearestQuery(userQuery, group.friendlyBrand));
      return;
    }
  }, [groups, userQuery, onClarify, onTraceId]);

  useEffect(() => {
    if (imageContexts.length > 0 || userQuery) {
      buildGroups();
    }
  }, [imageContexts, userQuery, buildGroups]);

  if (imageContexts.length === 0 && !userQuery) {
    return (
      <div className={styles.panel}>
        <div className={styles.empty}>Upload an image to see product recommendations.</div>
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      {/* Global red block */}
      {globalRedBlock && (
        <div className={styles.escalationBanner}>
          Multiple security signals detected. A security specialist is reviewing your session.
          Product recommendations are paused for your safety.
        </div>
      )}

      {/* Loading */}
      {loading && groups.length === 0 && (
        <div className={styles.loading}>
          <div className={styles.spinner} />
          <div>Finding the best matches...</div>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className={styles.empty}>Could not load recommendations. {error}</div>
      )}

      {/* Per-image groups */}
      {groups.map((group, idx) => {
        const trustClass = styles[`trust${group.trustLevel.charAt(0).toUpperCase() + group.trustLevel.slice(1)}`] || styles.trustGreen;
        return (
          <div key={`${group.source}-${idx}`} className={styles.anchorGroup}>
            {/* Group header */}
            <div className={styles.anchorHeader}>
              <span className={styles.anchorIcon}>{group.icon}</span>
              <span>{group.source}</span>
              <span className={`${styles.trustBadge} ${trustClass}`}>{groupStatusLabel(group)}</span>
              {group.domainBadge && <span className={styles.domainBadge}>{group.domainBadge}</span>}
              {group.fillBadge && <span className={styles.fillBadge}>{group.fillBadge}</span>}
              {group.verdictLabel && <span className={styles.domainBadge}>{group.verdictLabel}{group.confidenceBand ? ` • ${group.confidenceBand}` : ''}</span>}
            </div>

            {/* Security note — friendly, non-scary */}
            {group.securityNote && (
              <div className={group.trustLevel === 'green' ? styles.securityNoteBenign : styles.securityNote}>
                {group.securityNote}
                {/* Proof-of-purchase CTAs only in ownership-proof flows, never during normal shopping. */}
                {isProofRelevant(group, userQuery) && (
                  <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button className={styles.clarifyBtn} onClick={() => onClarify?.('I am uploading my receipt now')}>
                      Upload receipt
                    </button>
                    <button className={styles.clarifyBtn} onClick={() => onClarify?.('I am uploading my order confirmation screenshot now')}>
                      Upload order confirmation
                    </button>
                    <button className={styles.clarifyBtn} onClick={() => onClarify?.('I am uploading a photo of the serial number label now')}>
                      Upload serial label
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* ── Repair / Warranty card (damage intent detected) ── */}
            {group.isRepairIntent && (
              <div className={styles.securityNote} style={{ borderLeft: '4px solid #f97316', background: '#fff7ed' }}>
                <div style={{ fontWeight: 700, marginBottom: 6 }}>
                  🔧 This looks like a damaged {group.repairContext?.brand || group.friendlyBrand}.
                </div>
                <p style={{ margin: '0 0 8px' }}>Would you like to:</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <button className={styles.clarifyBtn} onClick={() => onClarify?.('Start a warranty or repair claim')}>
                    Start a warranty / repair claim
                  </button>
                  <button className={styles.clarifyBtn} onClick={() => onClarify?.('How do I return a damaged product?')}>
                    Check the return &amp; repair policy
                  </button>
                  <button className={styles.clarifyBtn} onClick={() => onClarify?.(`Find a ${group.repairContext?.brand || group.friendlyBrand} repair centre near me`)}>
                    Find a repair centre near me
                  </button>
                  <button className={styles.clarifyBtn} onClick={() => onClarify?.('What are my options for a cracked screen?')}>
                    FAQ: cracked screen options
                  </button>
                </div>
                <div style={{ marginTop: 10, fontSize: 12, color: '#92400e' }}>
                  📎 If you have a receipt or proof of purchase, upload it with your next message — or sign in to pull up your order history.
                </div>
              </div>
            )}

            {/* Red block for this image */}
            {group.trustLevel === 'red' && !group.isRepairIntent && (
              <div className={styles.escalationBanner}>
                Recommendations paused for this image due to security signals.
              </div>
            )}

            {/* Product cards — not shown for repair intent or red trust */}
            {!group.isRepairIntent && group.products.length > 0 && (
              <div className={styles.cardRow}>
                {group.products.map((p) => (
                  <div key={p.sku} className={styles.card}>
                    {(() => {
                      const title = productDisplayName(p);
                      const subtitle = productSubtitle(p);
                      return (
                        <>
                    <img
                      className={styles.cardImg}
                      src={p.image_url || `/static/images/${p.sku}.svg`}
                      alt={title}
                      onError={(e) => { (e.target as HTMLImageElement).src = '/static/images/placeholder.svg'; }}
                    />
                    <div className={styles.cardBody}>
                      <a className={styles.cardNameLink} href={`/ui/product/${encodeURIComponent(p.sku || '')}`} title={title}>
                        <div className={styles.cardName}>{title}</div>
                      </a>
                      <div className={styles.cardMeta}>{subtitle || p.specs_summary || '\u2014'}</div>
                      {(() => { const pros = buildProsNote(p, userQuery); return pros ? <div className={styles.cardFit}>{'✓ '}{pros}</div> : null; })()}
                      {p.use_case_fit && p.use_case_fit !== buildProsNote(p, userQuery) && <div className={styles.cardFit}>{p.use_case_fit}</div>}
                      {p.sku && <a className={styles.cardLink} href={`/ui/product/${encodeURIComponent(p.sku)}`}>View details</a>}
                    </div>
                    <div className={styles.cardPrice}>{formatPrice(p.price)}</div>
                    <button
                      className={styles.addBtn}
                      onClick={() => p.sku && onAdd?.(p.sku)}
                      disabled={!p.sku}
                      type="button"
                    >
                      Add to cart
                    </button>
                        </>
                      );
                    })()}
                  </div>
                ))}
              </div>
            )}

            {/* Budget widen — suppressed for security-locked and red lanes */}
            {group.widenState?.noResults && group.trustLevel !== 'red' && (
              <div className={styles.widenBox}>
                <div className={styles.widenText}>{group.offDomain ? group.summary : buildNoResultsText(group.friendlyBrand)}</div>
                {!group.offDomain && !/^product$/i.test(group.friendlyBrand) && (
                  <div className={styles.widenButtons}>
                    {WIDEN_STEPS.map((step) => (
                      <button key={step} className={styles.widenBtn} onClick={() => handleWiden(idx, step)}>
                        Widen +${step}
                      </button>
                    ))}
                    <button className={styles.widenBtnAlt} onClick={() => handleShowNearest(idx)}>
                      {buildNearestLabel(group.friendlyBrand)}
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* LLM Summary */}
            {group.summary && (
              <div className={styles.summary}>{group.summary}</div>
            )}
          </div>
        );
      })}

      {/* Clarifying questions */}
      {!loading && clarifyQuestions && (
        <div className={styles.clarifySection}>
          <div className={styles.clarifyPrompt}>{clarifyQuestions.prompt}</div>
          <div className={styles.clarifyOptions}>
            {clarifyQuestions.options.map((opt) => (
              <button key={opt} className={styles.clarifyBtn} onClick={() => onClarify?.(opt)}>
                {opt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* No results at all */}
      {!loading && !error && groups.length === 0 && !globalRedBlock && (
        <div className={styles.empty}>No product recommendations available yet. Try sending a query with your image.</div>
      )}
    </div>
  );
}
