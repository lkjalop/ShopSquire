import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ProcurementCertificationShowcase from '../ProcurementCertificationShowcase';


afterEach(() => vi.restoreAllMocks());

describe('ProcurementCertificationShowcase', () => {
  it('renders retained state, authority boundaries, and the artifact seal', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        passed: true,
        turns: ['Turn one procurement request', 'Move five from Perth to Sydney'],
        amended_state: {
          revision: 2,
          requested_quantity: 60,
          workloads: ['Unreal Engine', 'large CAD models', 'simulation'],
          destinations: [
            { location_ref: 'Sydney', quantity: 45 },
            { location_ref: 'Perth', quantity: 15 },
          ],
          budget: { amount_minor: 22000000 },
          temporal: {
            original_expression: 'within four days',
            resolved_utc_instant: '2026-08-24T00:00:00+00:00',
            interpretation_instant: '2026-08-20T00:00:00+00:00',
            timezone: 'Australia/Sydney', calendar_version: 'system-zoneinfo:Australia/Sydney',
            resolution_status: 'resolved', resolution_confidence: 1,
          },
        },
        allocation: { allocated_units: 41, requested_units: 60, shortfall_units: 19 },
        provider_accounting: { paid_calls: 0 },
        canonical_truth: {
          research_execution: 'COMPLETE', evidence_status: 'ACCEPTED_COMPLETE',
          freshness: 'CURRENT', decision_status: 'CONDITIONAL', commerce_authority: 'NONE',
        },
        artifact_sha256: 'a'.repeat(64),
      }),
    } as Response);

    render(<ProcurementCertificationShowcase />);

    const page = await screen.findByTestId('procurement-certification-showcase');
    expect(page).toHaveTextContent(/Language proposes. Deterministic state decides/i);
    expect(page).toHaveTextContent(/Sydney.*45 units/i);
    expect(page).toHaveTextContent(/Perth.*15 units/i);
    expect(page).toHaveTextContent(/supplier shortfall: 19 units/i);
    expect(page).toHaveTextContent(/No RFQ was sent and no stock was reserved/i);
    expect(page).toHaveTextContent(/Authority none/i);
    expect(page).toHaveTextContent('a'.repeat(64));
  });
});
