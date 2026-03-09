import { useEffect, useState, useCallback } from 'react';
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
}

/* ---------- constants ---------- */
const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
const DEFAULT_UID = ((import.meta as any).env?.VITE_DEFAULT_UID as string | undefined) || 'demo-user';
const WIDEN_STEPS = [200, 400];

/* ---------- helpers ---------- */
function computeTrustLevel(signals: ImageAnalysisContext['cv_signals'], sessionSuspicious: number): TrustLevel {
  if (sessionSuspicious >= 3 || signals.qr_prompt_injection) return 'red';
  if (sessionSuspicious >= 2 || signals.manipulation_detected) return 'orange';
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
function friendlyBrand(labels: string[], ocrText: string): string {
  const all = [...labels.map(l => l.toLowerCase()), ocrText.toLowerCase()];
  const joined = all.join(' ');
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

/** Clarifying questions based on detected use-case */
const CLARIFYING_QUESTIONS: Record<string, { prompt: string; options: string[] }> = {
  university: {
    prompt: 'What will you mainly use it for at uni?',
    options: ['Note-taking & lectures', 'Coding & development', 'Content creation', 'Light gaming', 'General uni work'],
  },
  office: {
    prompt: 'What kind of office work?',
    options: ['Emails & documents', 'Video calls & meetings', 'Data / spreadsheets', 'Light design work'],
  },
  general: {
    prompt: 'What will you mainly use this for?',
    options: ['University / study', 'Gaming', 'Office / work', 'Content creation', 'General browsing'],
  },
};

function formatPrice(cents_or_dollars: number): string {
  const val = cents_or_dollars > 200 ? cents_or_dollars / 100 : cents_or_dollars;
  return `$${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function parseProducts(data: any): ProductCard[] {
  const raw = data.results || data.products || [];
  return raw.map((p: any) => ({
    sku: p.sku || '',
    name: p.name || 'Unknown',
    price: p.price_cents ? p.price_cents / 100 : (p.price || 0),
    specs_summary: [p.specs?.cpu, p.specs?.ram_gb ? `${p.specs.ram_gb}GB` : null, p.specs?.gpu].filter(Boolean).join(' \u00B7 '),
    use_case_fit: p.use_case_suitability || p.use_case_fit || null,
    image_url: p.image_url || null,
  }));
}

async function fetchSuggest(query: string, ctx: ImageAnalysisContext | null, budgetMax?: number): Promise<{ products: ProductCard[]; summary: string; nextQuestions: any[] }> {
  const params = new URLSearchParams({ uid: DEFAULT_UID, query: query || 'show me laptops' });
  if (ctx) {
    params.set('image_labels', (ctx.labels || []).join(','));
    params.set('image_ocr_text', (ctx.ocr_text || '').slice(0, 500));
    params.set('image_cv_signals', JSON.stringify(ctx.cv_signals || {}));
  }
  if (budgetMax) params.set('budget_max', String(budgetMax));

  const resp = await fetch(apiUrl(`/api/v1/recommend/suggest?${params.toString()}`), {
    credentials: 'include',
    headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
  });
  const data = await safeJson(resp);
  if (!resp.ok || !data) throw new Error(data?.detail || `recommend_failed (${resp.status})`);
  return {
    products: parseProducts(data),
    summary: data.assistant_message || '',
    nextQuestions: Array.isArray(data.next_questions) ? data.next_questions : [],
  };
}

/* ---------- component ---------- */
export default function ImageRecommendPanel({ imageContexts, userQuery, traceId, sessionSuspiciousCount = 0, onClarify }: Props) {
  const [groups, setGroups] = useState<ImageGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarifyQuestions, setClarifyQuestions] = useState<{ prompt: string; options: string[] } | null>(null);
  const [globalRedBlock, setGlobalRedBlock] = useState(false);

  const buildGroups = useCallback(async () => {
    if (imageContexts.length === 0 && !userQuery) return;
    setLoading(true);
    setError(null);
    setGroups([]);
    setGlobalRedBlock(false);

    const built: ImageGroup[] = [];

    // One group per image
    for (let i = 0; i < imageContexts.length; i++) {
      const ctx = imageContexts[i];
      const trust = computeTrustLevel(ctx.cv_signals || {}, sessionSuspiciousCount);
      const brand = friendlyBrand(ctx.labels, ctx.ocr_text);
      const note = TRUST_NOTES[trust];

      if (trust === 'red') {
        built.push({
          source: ctx.source_name || `Image ${i + 1}: ${brand}`,
          icon: '\uD83D\uDCF8',
          trustLevel: trust,
          friendlyBrand: brand,
          securityNote: note,
          products: [],
          summary: '',
        });
        continue;
      }

      try {
        const imageQuery = `${userQuery} ${brand}`.trim();
        const result = await fetchSuggest(imageQuery, ctx);
        built.push({
          source: ctx.source_name || `Image ${i + 1}: ${brand}`,
          icon: '\uD83D\uDCF8',
          trustLevel: trust,
          friendlyBrand: brand,
          securityNote: note,
          products: result.products.slice(0, 3),
          summary: result.summary || `Top ${brand} picks matching your image.`,
        });
      } catch {
        built.push({
          source: ctx.source_name || `Image ${i + 1}: ${brand}`,
          icon: '\uD83D\uDCF8',
          trustLevel: trust,
          friendlyBrand: brand,
          securityNote: note,
          products: [],
          summary: `Could not load ${brand} recommendations.`,
        });
      }
    }

    // Query-intent group (if query adds context beyond image brands)
    if (userQuery) {
      try {
        const result = await fetchSuggest(userQuery, null);
        if (result.products.length > 0) {
          built.push({
            source: `From your query`,
            icon: '\uD83D\uDD0D',
            trustLevel: 'green',
            friendlyBrand: '',
            securityNote: '',
            products: result.products.slice(0, 3),
            summary: result.summary || `Products matching "${userQuery}".`,
          });
        } else {
          // No results — budget widen scenario
          built.push({
            source: `From your query`,
            icon: '\uD83D\uDD0D',
            trustLevel: 'green',
            friendlyBrand: '',
            securityNote: '',
            products: [],
            summary: result.summary || 'No products found in your budget range.',
            widenState: { budgetMin: 0, budgetMax: 0, noResults: true },
          });
        }
      } catch {
        /* query fetch failed — still show image groups */
      }
    }

    // Check if ALL groups are red
    if (built.length > 0 && built.every(g => g.trustLevel === 'red')) {
      setGlobalRedBlock(true);
    }

    // Clarifying questions
    const useCase = detectUseCase(userQuery);
    if (useCase && CLARIFYING_QUESTIONS[useCase]) {
      setClarifyQuestions(CLARIFYING_QUESTIONS[useCase]);
    } else if (!useCase && imageContexts.length > 0) {
      setClarifyQuestions(CLARIFYING_QUESTIONS.general);
    }

    setGroups(built);
    setLoading(false);
  }, [imageContexts, userQuery, sessionSuspiciousCount]);

  const handleWiden = useCallback(async (groupIdx: number, widenAmount: number) => {
    const group = groups[groupIdx];
    if (!group?.widenState) return;
    const newMax = (group.widenState.budgetMax || 1500) + widenAmount;
    try {
      const result = await fetchSuggest(userQuery, null, newMax);
      setGroups(prev => {
        const updated = [...prev];
        updated[groupIdx] = {
          ...updated[groupIdx],
          products: result.products.slice(0, 3),
          summary: result.summary || `Expanded budget to $${newMax.toLocaleString()}.`,
          widenState: result.products.length > 0
            ? undefined
            : { ...updated[groupIdx].widenState!, budgetMax: newMax, noResults: true },
        };
        return updated;
      });
    } catch { /* ignore */ }
  }, [groups, userQuery]);

  const handleShowNearest = useCallback(async (groupIdx: number) => {
    try {
      const result = await fetchSuggest(`${userQuery} any price`, null);
      setGroups(prev => {
        const updated = [...prev];
        updated[groupIdx] = {
          ...updated[groupIdx],
          products: result.products.slice(0, 3),
          summary: result.summary || 'Showing nearest available products at any price.',
          widenState: undefined,
        };
        return updated;
      });
    } catch { /* ignore */ }
  }, [userQuery]);

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
                      <div className={styles.cardName}>{p.name}</div>
                      <div className={styles.cardMeta}>{p.specs_summary || '\u2014'}</div>
                      {p.use_case_fit && <div className={styles.cardFit}>{p.use_case_fit}</div>}
                    </div>
                    <div className={styles.cardPrice}>{formatPrice(p.price)}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Budget widen */}
            {group.widenState?.noResults && group.trustLevel !== 'red' && (
              <div className={styles.widenBox}>
                <div className={styles.widenText}>No products found in your budget range.</div>
                <div className={styles.widenButtons}>
                  {WIDEN_STEPS.map((step) => (
                    <button key={step} className={styles.widenBtn} onClick={() => handleWiden(idx, step)}>
                      Widen +${step}
                    </button>
                  ))}
                  <button className={styles.widenBtnAlt} onClick={() => handleShowNearest(idx)}>
                    Show nearest
                  </button>
                </div>
              </div>
            )}

            {/* LLM Summary */}
            {group.summary && group.products.length > 0 && (
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
