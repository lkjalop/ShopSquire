export type ImageEvidenceResult = {
  _upload_error?: unknown;
  provider?: unknown;
  artifact?: { state?: unknown } | null;
  security?: {
    artifact_state?: unknown;
    commercial_authority?: unknown;
  } | null;
};

const NON_AUTHORITATIVE_STATES = new Set([
  'pending',
  'degraded',
  'quarantined',
  'superseded',
]);

/** Fail closed until uploaded evidence has completed inspection and authority. */
export function isUnusableImageEvidence(result: ImageEvidenceResult): boolean {
  const state = String(
    result?.artifact?.state || result?.security?.artifact_state || '',
  ).toLowerCase();
  return Boolean(result?._upload_error)
    || result?.provider === 'client_fast_boundary'
    || NON_AUTHORITATIVE_STATES.has(state)
    || result?.security?.commercial_authority === 'blocked';
}
