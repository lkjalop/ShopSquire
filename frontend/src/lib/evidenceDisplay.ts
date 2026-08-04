/**
 * Evidence-block display mapping (N1, 2026-07-07) — pure + unit-testable.
 *
 * The backend's evidence orchestrator returns {selected, legs, citations, ms}. This module turns that
 * into render-ready rows with the TRUST HIERARCHY the UI must communicate: internal legs (catalog,
 * policy, history…) are trusted records; external legs (web) are verified-untrusted evidence and get
 * distinct visual treatment. Order is trusted-first — the hierarchy IS the message.
 */

export type EvidenceLeg = {
  source?: string;
  found?: boolean;
  summary?: string;
  data?: Record<string, unknown>;
  error?: string;
};

export type EvidenceBlock = {
  selected?: string[];
  legs?: Record<string, EvidenceLeg>;
  citations?: { source?: string; summary?: string; trusted?: boolean }[];
  ms?: number;
};

type LegMeta = { icon: string; label: string; trusted: boolean };

// Keyed by BOTH the leg key and the leg's source label (the orchestrator emits e.g. key
// "availability" with source "inventory") so chips and rows resolve either way.
const _META: Record<string, LegMeta> = {
  market: { icon: '📈', label: 'Market intelligence', trusted: false },
  market_intelligence: { icon: '📈', label: 'Market intelligence', trusted: false },
  policy: { icon: '📚', label: 'Store policy', trusted: true },
  store_policy: { icon: '📚', label: 'Store policy', trusted: true },
  availability: { icon: '🏬', label: 'Inventory', trusted: true },
  inventory: { icon: '🏬', label: 'Inventory', trusted: true },
  purchase_history: { icon: '🧾', label: 'Purchase history', trusted: true },
  image: { icon: '🖼️', label: 'Photo identity', trusted: true },
  image_identity: { icon: '🖼️', label: 'Photo identity', trusted: true },
  web: { icon: '🌐', label: 'External web', trusted: false },
  external_web: { icon: '🌐', label: 'External web', trusted: false },
};

export function legMeta(keyOrSource: string): LegMeta {
  return _META[String(keyOrSource || '').toLowerCase()]
    || { icon: '📄', label: keyOrSource || 'Source', trusted: true };
}

export type EvidenceRow = {
  key: string;
  icon: string;
  label: string;
  trusted: boolean;
  found: boolean;
  summary: string;
  error: string;
};

/** Render-ready rows, trusted sources first, external last (the trust hierarchy is the ordering). */
export function evidenceRows(ev: EvidenceBlock | null | undefined): EvidenceRow[] {
  if (!ev || !ev.legs) return [];
  const rows: EvidenceRow[] = Object.entries(ev.legs).map(([key, leg]) => {
    const meta = legMeta((leg && leg.source) || key);
    const explicitlyVerified = leg && leg.data && leg.data.trust_state === 'verified_internal';
    return {
      key,
      icon: meta.icon,
      label: meta.label,
      trusted: meta.trusted || Boolean(explicitlyVerified),
      found: Boolean(leg && leg.found),
      summary: String((leg && leg.summary) || ''),
      error: String((leg && leg.error) || ''),
    };
  });
  return rows.sort((a, b) => Number(b.trusted) - Number(a.trusted) || a.label.localeCompare(b.label));
}

export type CitationChip = { key: string; icon: string; label: string; trusted: boolean };

/** Chips for the chat message footer — only legs that actually FOUND something get a chip. */
export function citationChips(ev: EvidenceBlock | null | undefined): CitationChip[] {
  if (!ev || !Array.isArray(ev.citations)) return [];
  return ev.citations
    .filter((c) => c && c.source)
    .map((c) => {
      const meta = legMeta(String(c.source));
      return {
        key: String(c.source), icon: meta.icon, label: meta.label,
        trusted: typeof c.trusted === 'boolean' ? c.trusted : meta.trusted,
      };
    });
}
