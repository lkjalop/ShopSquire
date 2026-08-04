/**
 * StorefrontEmphasisBanner — the M5 STOREFRONT lane made visible.
 *
 * Reads GET /market/storefront-emphasis (the demand-aware copy angle from sales_response_policy) and, when
 * the angle is VALUE or URGENCY, shows a small banner. FEATURES (the neutral default) renders nothing, so
 * the banner only appears when the market signal actually says something — it's a signal, not chrome.
 *
 * The decision is server-side + governed (policy → demand findings); this component only renders the angle.
 */
import { useEffect, useState } from 'react';
import { getStorefrontEmphasis } from '../lib/api';

const COPY: Record<string, { text: string; bg: string; fg: string; border: string }> = {
  urgency: { text: '🔥 In demand right now — the popular picks are moving fast.',
             bg: '#fef2f2', fg: '#991b1b', border: '#fecaca' },
  value: { text: '💰 Great value this week — strong picks are well within budget.',
           bg: '#f0fdf4', fg: '#166534', border: '#bbf7d0' },
};

export default function StorefrontEmphasisBanner() {
  const [angle, setAngle] = useState<string>('features');

  useEffect(() => {
    let alive = true;
    getStorefrontEmphasis('balanced')
      .then((d) => { if (alive && d?.messaging_emphasis) setAngle(String(d.messaging_emphasis)); })
      .catch(() => { /* best-effort — no banner on failure */ });
    return () => { alive = false; };
  }, []);

  const c = COPY[angle];
  if (!c) return null;   // FEATURES / unknown → render nothing
  return (
    <div data-testid="storefront-emphasis" role="status"
         style={{ margin: '0 0 12px', padding: '8px 14px', borderRadius: 8, fontWeight: 600,
                  background: c.bg, color: c.fg, border: `1px solid ${c.border}` }}>
      {c.text}
    </div>
  );
}
