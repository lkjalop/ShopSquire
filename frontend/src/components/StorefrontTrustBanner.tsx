import styles from './StorefrontTrustBanner.module.css';

export type CatalogueLoadState = 'loading' | 'ready' | 'empty' | 'unavailable';

export type TrustEvidence = {
  synthetic: boolean | null;
  shadow: boolean | null;
  humanApprovalRequired: boolean | null;
  provenance: string | null;
};

export function trustEvidenceFromPayload(payload: any): TrustEvidence {
  const evidence = payload?.evidence && typeof payload.evidence === 'object' ? payload.evidence : {};
  const catalogue = payload?.catalogue && typeof payload.catalogue === 'object' ? payload.catalogue : {};
  const mode = String(payload?.evaluation_mode || evidence?.evaluation_mode || '').trim().toLowerCase();
  const provenance = [
    payload?.catalogue_provenance,
    catalogue?.provenance,
    evidence?.catalogue_provenance,
  ].find((value) => typeof value === 'string' && value.trim());

  return {
    synthetic:
      payload?.synthetic === true || payload?.simulation_only === true || catalogue?.synthetic === true
        ? true
        : payload?.synthetic === false || payload?.simulation_only === false || catalogue?.synthetic === false
          ? false
          : null,
    shadow:
      payload?.shadow_mode === true || evidence?.shadow_mode === true || mode === 'shadow'
        ? true
        : payload?.shadow_mode === false || evidence?.shadow_mode === false || (mode && mode !== 'shadow')
          ? false
          : null,
    humanApprovalRequired:
      payload?.human_approval_required === true || payload?.approval_required === true || evidence?.human_approval_required === true
        ? true
        : payload?.human_approval_required === false || payload?.approval_required === false || evidence?.human_approval_required === false
          ? false
          : null,
    provenance: provenance ? String(provenance).trim() : null,
  };
}

type Props = {
  localEnvironment: boolean;
  catalogueState: CatalogueLoadState;
  evidence: TrustEvidence;
};

export default function StorefrontTrustBanner({ localEnvironment, catalogueState, evidence }: Props) {
  const catalogueLabel = catalogueState === 'loading'
    ? 'Catalogue loading'
    : catalogueState === 'unavailable'
      ? 'Catalogue unavailable'
      : catalogueState === 'empty'
        ? 'Catalogue empty'
        : 'Catalogue loaded';

  return (
    <aside className={styles.banner} aria-label="Demo and evidence status" data-testid="storefront-trust-banner">
      <strong>Evidence status</strong>
      <span className={styles.items}>
        {localEnvironment && <span className={styles.local}>Local development</span>}
        <span>{catalogueLabel}</span>
        <span>
          {evidence.synthetic === true
            ? 'Synthetic data declared'
            : evidence.synthetic === false
              ? 'Synthetic flag: no'
              : 'Synthetic status not supplied'}
        </span>
        <span>
          {evidence.shadow === true
            ? 'Shadow evaluation declared'
            : evidence.shadow === false
              ? 'Shadow mode: no'
              : 'Shadow status not supplied'}
        </span>
        <span>
          {evidence.humanApprovalRequired === true
            ? 'Human approval required'
            : evidence.humanApprovalRequired === false
              ? 'Human approval: not required'
              : 'Approval status not supplied'}
        </span>
        <span>{evidence.provenance ? `Provenance: ${evidence.provenance}` : 'Catalogue provenance not supplied'}</span>
      </span>
    </aside>
  );
}

