import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import StorefrontTrustBanner, { trustEvidenceFromPayload } from '../StorefrontTrustBanner';

describe('StorefrontTrustBanner', () => {
  it('reports unknown evidence instead of inferring synthetic, shadow, or approval status', () => {
    render(
      <StorefrontTrustBanner
        localEnvironment
        catalogueState="ready"
        evidence={trustEvidenceFromPayload(null)}
      />,
    );

    const banner = screen.getByTestId('storefront-trust-banner');
    expect(banner).toHaveTextContent('Local development');
    expect(banner).toHaveTextContent('Catalogue loaded');
    expect(banner).toHaveTextContent('Synthetic status not supplied');
    expect(banner).toHaveTextContent('Shadow status not supplied');
    expect(banner).toHaveTextContent('Approval status not supplied');
    expect(banner).toHaveTextContent('Catalogue provenance not supplied');
  });

  it('only displays declared payload evidence', () => {
    const evidence = trustEvidenceFromPayload({
      simulation_only: true,
      evaluation_mode: 'shadow',
      human_approval_required: true,
      catalogue_provenance: 'fixture:wholesale-v1',
    });

    render(
      <StorefrontTrustBanner
        localEnvironment={false}
        catalogueState="unavailable"
        evidence={evidence}
      />,
    );

    const banner = screen.getByLabelText('Demo and evidence status');
    expect(banner).toHaveTextContent('Synthetic data declared');
    expect(banner).toHaveTextContent('Shadow evaluation declared');
    expect(banner).toHaveTextContent('Human approval required');
    expect(banner).toHaveTextContent('Provenance: fixture:wholesale-v1');
    expect(banner).toHaveTextContent('Catalogue unavailable');
    expect(banner).not.toHaveTextContent('Local development');
  });
});

