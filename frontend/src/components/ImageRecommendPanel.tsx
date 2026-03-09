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
}

interface ProductCard {
  sku: string;
  name: string;
  price: number;
  specs_summary?: string;
  gaming_rating?: string;
  image_url?: string;
}

interface AnchorGroup {
  anchor: string;
  icon: string;
  products: ProductCard[];
  summary: string;
}

type TrustLevel = 'green' | 'yellow' | 'orange' | 'red';

interface Props {
  imageContext: ImageAnalysisContext | null;
  userQuery: string;
  traceId?: string | null;
  /** Cumulative count of suspicious uploads in this session */
  sessionSuspiciousCount?: number;
}

/* ---------- constants ---------- */
const API_KEY = ((import.meta as any).env?.VITE_API_KEY as string | undefined) || '';
const DEFAULT_UID = ((import.meta as any).env?.VITE_DEFAULT_UID as string | undefined) || 'demo-user';

/* ---------- helpers ---------- */
function computeTrustLevel(signals: ImageAnalysisContext['cv_signals'], sessionSuspicious: number): TrustLevel {
  if (sessionSuspicious >= 3 || signals.qr_prompt_injection) return 'red';
  if (sessionSuspicious >= 2 || signals.manipulation_detected) return 'orange';
  if (signals.qr_code_detected) return 'yellow';
  return 'green';
}

const TRUST_LABELS: Record<TrustLevel, string> = {
  green: 'Trusted',
  yellow: 'Monitoring',
  orange: 'Under Review',
  red: 'Escalated',
};

function formatPrice(cents_or_dollars: number): string {
  const val = cents_or_dollars > 200 ? cents_or_dollars / 100 : cents_or_dollars;
  return `$${val.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

/* ---------- component ---------- */
export default function ImageRecommendPanel({ imageContext, userQuery, traceId, sessionSuspiciousCount = 0 }: Props) {
  const [anchors, setAnchors] = useState<AnchorGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trustLevel, setTrustLevel] = useState<TrustLevel>('green');

  const fetchRecommendations = useCallback(async (ctx: ImageAnalysisContext, query: string) => {
    setLoading(true);
    setError(null);
    setAnchors([]);

    const trust = computeTrustLevel(ctx.cv_signals, sessionSuspiciousCount);
    setTrustLevel(trust);

    // If red-level trust, don't fetch recommendations
    if (trust === 'red') {
      setLoading(false);
      return;
    }

    try {
      const params = new URLSearchParams({
        uid: DEFAULT_UID,
        query: query || 'show me laptops',
        image_labels: (ctx.labels || []).join(','),
        image_ocr_text: (ctx.ocr_text || '').slice(0, 500),
        image_cv_signals: JSON.stringify(ctx.cv_signals || {}),
      });

      const resp = await fetch(apiUrl(`/api/v1/recommend/suggest?${params.toString()}`), {
        credentials: 'include',
        headers: API_KEY ? { 'x-api-key': API_KEY } : undefined,
      });

      const data = await safeJson(resp);
      if (!resp.ok || !data) {
        throw new Error(data?.detail || `recommend_failed (${resp.status})`);
      }

      // Build anchor groups from the response
      const products: ProductCard[] = (data.products || []).map((p: any) => ({
        sku: p.sku || '',
        name: p.name || 'Unknown',
        price: p.price_cents ? p.price_cents / 100 : (p.price || 0),
        specs_summary: [p.specs?.cpu, p.specs?.ram_gb ? `${p.specs.ram_gb}GB` : null, p.specs?.gpu].filter(Boolean).join(' · '),
        gaming_rating: p.gaming_rating || p.use_case_fit || null,
        image_url: p.image_url || null,
      }));

      // Determine what anchors to show based on image labels and query
      const queryLower = (query || '').toLowerCase();
      const labelStr = (ctx.labels || []).join(' ').toLowerCase();
      const isGamingQuery = /gaming|game|fps|rtx|gpu/i.test(queryLower);
      const isMacQuery = /mac|macbook|apple/i.test(queryLower) || /mac|macbook|apple/i.test(labelStr);

      const groups: AnchorGroup[] = [];

      if (isMacQuery && products.length > 0) {
        // Anchor 1: MacBook matches
        const macProducts = products.filter(p => /mac|apple/i.test(p.name));
        const otherProducts = products.filter(p => !/mac|apple/i.test(p.name));

        if (macProducts.length > 0) {
          groups.push({
            anchor: 'MacBook (from image)',
            icon: '\uD83D\uDCF8',
            products: macProducts.slice(0, 3),
            summary: isGamingQuery
              ? 'MacBooks use Apple Silicon without discrete GPUs. Lighter games run well, but AAA titles like Cyberpunk or Space Marine 2 need dedicated graphics.'
              : 'These MacBooks match your uploaded image. Great for productivity, creative work, and everyday use.',
          });
        }

        if (isGamingQuery && otherProducts.length > 0) {
          const gamingProducts = otherProducts.filter(p =>
            /gaming|rog|legion|raider|predator|rtx|gtx/i.test(p.name) || /rtx|gtx|radeon/i.test(p.specs_summary || '')
          );
          if (gamingProducts.length > 0) {
            groups.push({
              anchor: 'Gaming Alternatives',
              icon: '\uD83C\uDFAE',
              products: gamingProducts.slice(0, 3),
              summary: 'These laptops have dedicated GPUs for AAA gaming. The best value picks run Cyberpunk 2077 and Space Marine 2 at High/Ultra settings.',
            });
          }
        }

        // Anchor 3: Versatile options
        const versatileProducts = otherProducts.filter(p =>
          !/gaming|rog|legion|raider|predator/i.test(p.name)
        );
        if (versatileProducts.length > 0) {
          groups.push({
            anchor: 'Versatile (Uni / Office)',
            icon: '\uD83D\uDCDA',
            products: versatileProducts.slice(0, 3),
            summary: 'If your priority is portability and battery life for university or office work, these offer the best balance.',
          });
        }
      }

      // Fallback: if no specific anchors matched, show single group
      if (groups.length === 0 && products.length > 0) {
        groups.push({
          anchor: 'Top Matches',
          icon: '\uD83D\uDD0D',
          products: products.slice(0, 6),
          summary: data.assistant_message || `Found ${products.length} products matching your image and query.`,
        });
      }

      setAnchors(groups);
    } catch (e: any) {
      setError(e?.message || 'Failed to fetch recommendations');
    } finally {
      setLoading(false);
    }
  }, [sessionSuspiciousCount]);

  useEffect(() => {
    if (imageContext && (imageContext.labels.length > 0 || imageContext.ocr_text)) {
      fetchRecommendations(imageContext, userQuery);
    }
  }, [imageContext, userQuery, fetchRecommendations]);

  if (!imageContext) {
    return (
      <div className={styles.panel}>
        <div className={styles.empty}>Upload an image to see product recommendations.</div>
      </div>
    );
  }

  const signals = imageContext.cv_signals || {};
  const trustClass = styles[`trust${trustLevel.charAt(0).toUpperCase() + trustLevel.slice(1)}` as keyof typeof styles] || styles.trustGreen;

  return (
    <div className={styles.panel}>
      {/* Image Analysis Summary */}
      <div className={styles.imageAnalysis}>
        <h4>
          Image Analysis
          <span className={`${styles.trustBadge} ${trustClass}`}>{TRUST_LABELS[trustLevel]}</span>
        </h4>
        <div className={styles.analysisMeta}>
          {imageContext.labels.slice(0, 4).map(l => (
            <span key={l} className={`${styles.metaTag} ${styles.metaTagOk}`}>{l}</span>
          ))}
          {signals.qr_code_detected && (
            <span className={`${styles.metaTag} ${styles.metaTagWarn}`}>QR detected</span>
          )}
          {signals.manipulation_detected && (
            <span className={`${styles.metaTag} ${styles.metaTagDanger}`}>Manipulation</span>
          )}
          {signals.qr_prompt_injection && (
            <span className={`${styles.metaTag} ${styles.metaTagDanger}`}>Prompt injection</span>
          )}
        </div>
        {trustLevel === 'yellow' && (
          <div className={styles.securityNote}>
            QR code detected but content appears benign. Showing recommendations normally.
          </div>
        )}
        {trustLevel === 'orange' && (
          <div className={styles.securityNote}>
            Suspicious signals detected. An admin has been notified. Recommendations shown with caution.
          </div>
        )}
      </div>

      {/* Escalation Banner */}
      {trustLevel === 'red' && (
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

      {/* Anchor Groups */}
      {!loading && anchors.map((group) => (
        <div key={group.anchor} className={styles.anchorGroup}>
          <div className={styles.anchorHeader}>
            <span className={styles.anchorIcon}>{group.icon}</span>
            {group.anchor}
          </div>
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
                <div className={styles.cardMeta}>{p.specs_summary || '—'}</div>
                {p.gaming_rating && <div className={styles.cardRating}>{p.gaming_rating}</div>}
              </div>
              <div className={styles.cardPrice}>{formatPrice(p.price)}</div>
            </div>
          ))}
          <div className={styles.summary}>{group.summary}</div>
        </div>
      ))}

      {/* No results */}
      {!loading && !error && anchors.length === 0 && trustLevel !== 'red' && (
        <div className={styles.empty}>No product recommendations available yet. Try sending a query with your image.</div>
      )}
    </div>
  );
}
