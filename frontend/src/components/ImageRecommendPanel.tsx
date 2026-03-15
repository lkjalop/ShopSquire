import { useEffect, useState, useCallback, useRef } from 'react';
import { apiUrl, safeJson } from '../lib/api';
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
}

interface ProductCard {
  sku: string;
  name: string;
  price: number;
  specs_summary?: string;
  use_case_fit?: string;
  image_url?: string;
}

interface ImageGroup {
  /** Which image / query spawned this group */
  source: string;
  icon: string;
  trustLevel: TrustLevel;
  friendlyBrand: string;
  securityNote: string;
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
}

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
}

/* ---------- constants ---------- */
const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
const DEFAULT_UID = ((import.meta as any).env?.VITE_DEFAULT_UID as string | undefined) || 'demo-user';
const WIDEN_STEPS = [200, 400];
const RECOMMEND_TIMEOUT_MS = 7000;

function persistOperatorMetrics(timing: any, traceId: string | null, source = 'visual_search') {
  if (!timing || typeof timing !== 'object') return;
  try {
    localStorage.setItem('shopsquire_operator_metrics', JSON.stringify({
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
  if (sessionSuspicious >= 3 || signals.qr_prompt_injection) return 'red';
  if (signals.qr_external_url_detected) return 'orange';
  if (sessionSuspicious >= 2 || signals.manipulation_detected || signals.steg_suspicious) return 'orange';
  if (signals.qr_code_detected) return 'yellow';
  return 'green';
}

const TRUST_LABELS: Record<TrustLevel, string> = {
  green: 'Benign',
  yellow: 'Monitoring',
  orange: 'Under Review',
  red: 'Escalated',
};

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
  if (/universit|uni\b|college|school|student|lecture|study/i.test(q)) return 'university';
  if (/gaming|game|fps|rtx|gpu/i.test(q)) return 'gaming';
  if (/cod(e|ing)|develop|program/i.test(q)) return 'coding';
  if (/content|creat|video|edit|design|photo/i.test(q)) return 'content_creation';
  if (/office|admin|work|excel|zoom|teams|meet/i.test(q)) return 'office';
  return null;
}

/** Default budget ceiling (AUD cents * 100 → display dollars) for a given use-case. */
const USE_CASE_BUDGET: Record<string, number> = {
  university: 1200,
  coding: 1500,
  gaming: 2000,
  content_creation: 1800,
  office: 900,
};

/** Derive a short pros note from product specs + price. */
function buildProsNote(p: ProductCard, userQuery: string): string {
  const pros: string[] = [];
  const q = userQuery.toLowerCase();
  const specs = p.specs_summary || '';
  if (/\b16\s*gb/i.test(specs)) pros.push('16 GB RAM');
  else if (/\b8\s*gb/i.test(specs)) pros.push('8 GB RAM');
  if (/1\s*tb/i.test(specs)) pros.push('1 TB storage');
  else if (/512/i.test(specs)) pros.push('512 GB SSD');
  if (/oled/i.test(p.name)) pros.push('OLED display');
  if (/touch/i.test(p.name)) pros.push('Touchscreen');
  if (/rtx|gtx|radeon/i.test(specs)) pros.push('Discrete GPU');
  if (/universit|student/i.test(q) && p.price < 1000) pros.push('Student-budget friendly');
  if (/gaming/i.test(q) && /rtx/i.test(specs)) pros.push('Gaming-ready GPU');
  return pros.slice(0, 3).join(' · ');
}

/** Clarifying questions based on detected use-case */
const CLARIFYING_QUESTIONS: Record<string, { prompt: string; options: string[] }> = {
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
    price,
    specs_summary: specsSummary || undefined,
    use_case_fit: raw.use_case_suitability || raw.use_case_fit || raw.reason || null,
    image_url: raw.image_url || null,
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
  if (!brand) return 'No products found in your budget range.';
  if (/^product$/i.test(brand)) return 'This image does not look like a laptop product photo. Try a clearer device image or use a text query.';
  if (/^macbook$/i.test(brand)) return 'No MacBook products found in your budget range.';
  return `No ${brand} products found in your budget range.`;
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
    if (raw && /catalog|unrelated products|does not match this merchant/i.test(raw)) return raw;
    return buildNoResultsText(brand);
  }
  const useCase =
    /highschool|high school|student|university|uni|college/i.test(query) ? 'study' :
    /gaming|fps|gpu|rtx/i.test(query) ? 'gaming' :
    /work|office|meeting|excel/i.test(query) ? 'work' : 'daily use';
  const top = products.slice(0, 2).map((p) => {
    const why = _prettyReason(p.use_case_fit || '');
    return why ? `${p.name} (${why})` : p.name;
  });
  const r = raw.replace(/\(\s*[+-]?[a-z_]+(?:\s*,\s*[+-]?[a-z_]+)*\s*\)/gi, '').trim();
  if (r && r.length < 180) return r;
  return `Best ${useCase} picks here are ${top.join(' and ')}.`;
}

async function fetchSuggest(
  query: string,
  ctx: ImageAnalysisContext | null,
  budgetMax?: number,
): Promise<{ products: ProductCard[]; summary: string; nextQuestions: any[]; traceId: string | null; offDomain: boolean; lowSupport: boolean; domainBadge: string | null; fillBadge: string | null }> {
  const params = new URLSearchParams({ uid: DEFAULT_UID, query: query || 'show me laptops' });
  if (ctx) {
    const labels = [...(ctx.labels || [])];
    const srcName = String(ctx.source_name || '').toLowerCase();
    if (srcName) labels.push(srcName.replace(/\.[a-z0-9]+$/i, ''));
    params.set('image_labels', labels.join(','));
    params.set('image_ocr_text', (ctx.ocr_text || '').slice(0, 500));
    params.set('image_cv_signals', JSON.stringify(ctx.cv_signals || {}));
  }
  if (budgetMax) params.set('budget_max', String(budgetMax));
  params.set('copywriting_enabled', 'false');
  params.set('fast_path', 'true');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), RECOMMEND_TIMEOUT_MS);

  try {
    const resp = await fetch(apiUrl(`/api/v1/recommend/suggest?${params.toString()}`), {
      credentials: 'include',
      headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
      signal: controller.signal,
    });
    const data = await safeJson(resp);
    if (!resp.ok || !data) throw new Error(data?.detail || `recommend_failed (${resp.status})`);
    persistOperatorMetrics(
      data?.timing_breakdown,
      data.decision_trace_id || data.trace_id || data.decision_id || null,
      ctx ? 'visual_search' : 'text_fallback',
    );
    return {
      products: parseProducts(data),
      summary: data.assistant_message || '',
      nextQuestions: Array.isArray(data.next_questions) ? data.next_questions : [],
      traceId: data.decision_trace_id || data.trace_id || data.decision_id || null,
      offDomain: Boolean(data?.catalog_relevance?.off_domain),
      lowSupport: Boolean(data?.catalog_relevance?.low_support),
      domainBadge: data?.catalog_relevance?.off_domain
        ? (data?.catalog_relevance?.low_support ? 'Low catalog support' : 'Off-domain image')
        : null,
      fillBadge: data?.image_lane_fill?.applied
        ? `Filled to 3 using in-catalog ${String(data?.image_lane_fill?.image_category || 'catalog')} alternatives`
        : null,
    };
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error(`recommend_timeout_${RECOMMEND_TIMEOUT_MS}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

/* ---------- component ---------- */
export default function ImageRecommendPanel({ imageContexts, userQuery, traceId, sessionSuspiciousCount = 0, onClarify, onTraceId, onAdd }: Props) {
  const [groups, setGroups] = useState<ImageGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarifyQuestions, setClarifyQuestions] = useState<{ prompt: string; options: string[] } | null>(null);
  const [globalRedBlock, setGlobalRedBlock] = useState(false);
  const buildSeqRef = useRef(0);
  const lastBuildKeyRef = useRef('');

  const runBrandFallbackChain = useCallback(async (
    baseQuery: string,
    brandLabel: string,
    ctx: ImageAnalysisContext | null,
    budgetMax?: number,
  ) => {
    const cleanBase = stripBudgetHints(baseQuery);
    const apple = isAppleLikeBrand(brandLabel);
    const windows = isWindowsLikeBrand(brandLabel);
    if (!apple && !windows) return null;
    const profile = apple ? 'apple macbook' : 'windows laptop';

    const baseMax = Number.isFinite(Number(budgetMax)) ? Number(budgetMax) : 1200;
    const steps = apple ? [400, 800] : [400, 800, 1400];
    for (const step of steps) {
      const raisedMax = baseMax + step;
      const r2 = await fetchSuggest(`${cleanBase} ${profile} show nearest in-stock options above budget`.trim(), ctx, raisedMax);
      if ((r2.products || []).length > 0) {
        return {
          ...r2,
          summary: r2.summary || (
            apple
              ? `No in-budget MacBook found. Showing nearest MacBook options up to $${raisedMax.toLocaleString()}.`
              : `No in-budget Windows option found. Showing nearest Windows options up to $${raisedMax.toLocaleString()}.`
          ),
        };
      }
    }

    return fetchSuggest(
      `${cleanBase} show nearest in-stock alternatives`.trim(),
      ctx,
      baseMax + (apple ? 800 : 1600),
    );
  }, []);

  const buildGroups = useCallback(async () => {
    if (imageContexts.length === 0 && !userQuery) return;
    const buildKey = JSON.stringify({
      q: String(userQuery || ''),
      s: sessionSuspiciousCount,
      imgs: imageContexts.map((ctx) => ({
        src: ctx.source_name || '',
        labels: ctx.labels || [],
        ocr: String(ctx.ocr_text || '').slice(0, 160),
        signals: ctx.cv_signals || {},
      })),
    });
    if (buildKey === lastBuildKeyRef.current) return;
    lastBuildKeyRef.current = buildKey;
    const buildSeq = ++buildSeqRef.current;
    setLoading(true);
    setError(null);
    setGroups([]);
    setGlobalRedBlock(false);

    const built: ImageGroup[] = [];
    let firstTraceId: string | null = null;
    // Auto-budget: derive a sensible ceiling from the detected use-case when none explicit
    const useCase = detectUseCase(userQuery);
    const autoBudget = useCase ? USE_CASE_BUDGET[useCase] ?? 1200 : undefined;
    const parsedBudgetMax = extractBudgetMax(userQuery, autoBudget);

    // One group per image (parallelized so one slow image does not block the others)
    const perImage = await Promise.all(
      imageContexts.map(async (ctx, i) => {
        const trust = computeTrustLevel(ctx.cv_signals || {}, sessionSuspiciousCount);
        const brand = friendlyBrand(ctx.labels, ctx.ocr_text, ctx.source_name, userQuery);
        const note = TRUST_NOTES[trust];

        if (trust === 'red') {
          return {
            group: {
              source: ctx.source_name || `Image ${i + 1}: ${brand}`,
              icon: '\uD83D\uDCF8',
              trustLevel: trust,
              friendlyBrand: brand,
              securityNote: note,
              products: [],
              summary: '',
              context: ctx,
              lowSupport: false,
              domainBadge: null,
              fillBadge: null,
            } as ImageGroup,
            traceId: null as string | null,
          };
        }

        try {
          const base = stripBudgetHints(userQuery);
          const addLaptopToken = !/\blaptop|notebook|computer|pc|macbook|chromebook\b/i.test(base) && !/^product$/i.test(brand);
          const imageQuery = `${base} ${addLaptopToken ? 'laptop' : ''} ${brand}`.trim();
          const result = await fetchSuggest(imageQuery, ctx, parsedBudgetMax);
          let pickedTraceId: string | null = result.traceId || null;
          let products = result.products.slice(0, 3);
          let safeSummary = sanitizeSummary(result.summary, products.length, `Top ${brand} picks matching your image.`);
          let trustLevel = trust;
          let securityNote = note;
          if (products.length === 0 && !result.offDomain) {
            const chain = await runBrandFallbackChain(userQuery, brand, ctx, parsedBudgetMax);
            if (chain) {
              pickedTraceId = pickedTraceId || chain.traceId || null;
              products = (chain.products || []).slice(0, 3);
              safeSummary = sanitizeSummary(chain.summary, products.length, `Top ${brand} picks matching your image.`);
            }
          }
          if (result.offDomain) {
            trustLevel = trust === 'red' ? trust : 'orange';
            securityNote = 'Uploaded image appears outside the current merchant catalog. No unrelated substitutions were made.';
            products = [];
          }
          if (products.length === 0 && assistantClaimsProducts(safeSummary)) {
            safeSummary = 'No products found in your budget range.';
          }
          safeSummary = naturalSummary(safeSummary, products, userQuery, brand);
          return {
            group: {
              source: ctx.source_name || `Image ${i + 1}: ${brand}`,
              icon: '\uD83D\uDCF8',
              trustLevel,
              friendlyBrand: brand,
              securityNote,
              products,
              summary: safeSummary,
              widenState: products.length === 0 ? { budgetMin: 0, budgetMax: parsedBudgetMax ?? 1200, noResults: true } : undefined,
              context: ctx,
              offDomain: result.offDomain,
              lowSupport: result.lowSupport,
              domainBadge: result.domainBadge,
              fillBadge: result.fillBadge,
            } as ImageGroup,
            traceId: pickedTraceId,
          };
        } catch (e: any) {
          const timeoutMsg = String(e?.message || '').includes('recommend_timeout_')
            ? `Timed out loading ${brand} recommendations.`
            : `Could not load ${brand} recommendations.`;
          return {
            group: {
              source: ctx.source_name || `Image ${i + 1}: ${brand}`,
              icon: '\uD83D\uDCF8',
              trustLevel: trust,
              friendlyBrand: brand,
              securityNote: note,
              products: [],
              summary: timeoutMsg,
              widenState: { budgetMin: 0, budgetMax: parsedBudgetMax ?? 1200, noResults: true },
              context: ctx,
              lowSupport: false,
              domainBadge: null,
              fillBadge: null,
            } as ImageGroup,
            traceId: null as string | null,
          };
        }
      }),
    );
    for (const item of perImage) {
      built.push(item.group);
      if (!firstTraceId && item.traceId) firstTraceId = item.traceId;
    }

    // Query-intent group (if query adds context beyond image brands)
    if (userQuery && imageContexts.length === 0) {
      try {
        const result = await fetchSuggest(stripBudgetHints(userQuery), null, parsedBudgetMax);
        if (!firstTraceId && result.traceId) { firstTraceId = result.traceId; onTraceId?.(result.traceId); }
        let products = result.products.slice(0, 3);
        let safeSummary = sanitizeSummary(
          result.summary,
          products.length,
          products.length > 0 ? `Products matching "${userQuery}".` : 'No products found in your budget range.',
        );
        if (products.length === 0 && assistantClaimsProducts(safeSummary)) {
          safeSummary = 'No products found in your budget range.';
        }
        built.push({
          source: `From your query`,
          icon: '\uD83D\uDD0D',
          trustLevel: 'green',
          friendlyBrand: '',
          securityNote: '',
          products,
          summary: safeSummary,
          widenState: products.length === 0 ? { budgetMin: 0, budgetMax: parsedBudgetMax ?? 1200, noResults: true } : undefined,
          context: null,
          lowSupport: false,
          domainBadge: null,
          fillBadge: null,
        });
      } catch {
        /* query fetch failed — still show image groups */
      }
    }

    if (buildSeq !== buildSeqRef.current) return;
    if (firstTraceId) onTraceId?.(firstTraceId);

    // Check if ALL groups are red
    if (built.length > 0 && built.every(g => g.trustLevel === 'red')) {
      setGlobalRedBlock(true);
    }

    // Clarifying questions
    if (useCase && CLARIFYING_QUESTIONS[useCase]) {
      setClarifyQuestions(CLARIFYING_QUESTIONS[useCase]);
    } else if (!useCase && imageContexts.length > 0) {
      setClarifyQuestions(CLARIFYING_QUESTIONS.general);
    }

    setGroups(built);
    setLoading(false);
  }, [imageContexts, userQuery, sessionSuspiciousCount, onTraceId, runBrandFallbackChain]);

  const handleWiden = useCallback(async (groupIdx: number, widenAmount: number) => {
    const group = groups[groupIdx];
    if (!group?.widenState) return;
    const newMax = (group.widenState.budgetMax || 1500) + widenAmount;
    try {
      const widenedQuery = `${stripBudgetHints(userQuery)} ${group.friendlyBrand || ''}`.trim();
      const result = await fetchSuggest(widenedQuery, group.context || null, newMax);
      setGroups(prev => {
        const updated = [...prev];
        const nextProducts = result.products.slice(0, 3);
        updated[groupIdx] = {
          ...updated[groupIdx],
          products: nextProducts,
          summary: sanitizeSummary(result.summary, nextProducts.length, `Expanded budget to $${newMax.toLocaleString()}.`),
          widenState: nextProducts.length > 0
            ? undefined
            : { ...updated[groupIdx].widenState!, budgetMax: newMax, noResults: true },
        };
        return updated;
      });
      if (result.traceId) onTraceId?.(result.traceId);
    } catch { /* ignore */ }
  }, [groups, userQuery, onTraceId]);

  const handleShowNearest = useCallback(async (groupIdx: number) => {
    const group = groups[groupIdx];
    if (!group) return;
    try {
      const baseMax = group.widenState?.budgetMax || extractBudgetMax(userQuery, 1200) || 1200;
      const nearestBudgetMax = Math.max(1800, baseMax + 1200);
      const nearestQuery = buildNearestQuery(userQuery, group.friendlyBrand);
      const result = await fetchSuggest(nearestQuery, group.context || null, nearestBudgetMax);
      setGroups(prev => {
        const updated = [...prev];
        const nextProducts = result.products.slice(0, 3);
        updated[groupIdx] = {
          ...updated[groupIdx],
          products: nextProducts,
          summary: sanitizeSummary(
            result.summary,
            nextProducts.length,
            `${buildNearestLabel(group.friendlyBrand).replace(/^Show /, 'Showing ')} up to $${nearestBudgetMax.toLocaleString()}.`,
          ),
          widenState: nextProducts.length > 0 ? undefined : { budgetMin: 0, budgetMax: 0, noResults: true },
        };
        return updated;
      });
      if (result.traceId) onTraceId?.(result.traceId);
    } catch { /* ignore */ }
  }, [groups, userQuery, onTraceId]);

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
      {loading && (
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
      {!loading && groups.map((group, idx) => {
        const trustClass = styles[`trust${group.trustLevel.charAt(0).toUpperCase() + group.trustLevel.slice(1)}`] || styles.trustGreen;
        return (
          <div key={`${group.source}-${idx}`} className={styles.anchorGroup}>
            {/* Group header */}
            <div className={styles.anchorHeader}>
              <span className={styles.anchorIcon}>{group.icon}</span>
              <span>{group.source}</span>
              <span className={`${styles.trustBadge} ${trustClass}`}>{TRUST_LABELS[group.trustLevel]}</span>
              {group.domainBadge && <span className={styles.domainBadge}>{group.domainBadge}</span>}
              {group.fillBadge && <span className={styles.fillBadge}>{group.fillBadge}</span>}
            </div>

            {/* Security note — friendly, non-scary */}
            {group.securityNote && (
              <div className={group.trustLevel === 'green' ? styles.securityNoteBenign : styles.securityNote}>
                {group.securityNote}
              </div>
            )}

            {/* Red block for this image */}
            {group.trustLevel === 'red' && (
              <div className={styles.escalationBanner}>
                Recommendations paused for this image due to security signals.
              </div>
            )}

            {/* Product cards */}
            {group.products.length > 0 && (
              <div className={styles.cardRow}>
                {group.products.map((p) => (
                  <div key={p.sku} className={styles.card}>
                    <img
                      className={styles.cardImg}
                      src={p.image_url || `/static/images/${p.sku}.svg`}
                      alt={p.name}
                      onError={(e) => { (e.target as HTMLImageElement).src = '/static/images/placeholder.svg'; }}
                    />
                    <div className={styles.cardBody}>
                      <a className={styles.cardNameLink} href={`/ui/product/${encodeURIComponent(p.sku || '')}`} title={p.name}>
                        <div className={styles.cardName}>{p.name}</div>
                      </a>
                      <div className={styles.cardMeta}>{p.specs_summary || '\u2014'}</div>
                      {(() => { const pros = buildProsNote(p, userQuery); return pros ? <div className={styles.cardFit}>\u2713 {pros}</div> : null; })()}
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
                  </div>
                ))}
              </div>
            )}

            {/* Budget widen */}
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
