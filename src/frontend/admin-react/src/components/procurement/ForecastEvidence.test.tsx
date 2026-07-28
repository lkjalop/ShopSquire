import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ForecastEvidence from './ForecastEvidence';
import {
  fetchInventoryForecast,
  materializeInventoryForecast,
} from '../../api/fulfillment';

vi.mock('../../api/fulfillment', () => ({
  fetchInventoryForecast: vi.fn(),
  materializeInventoryForecast: vi.fn(),
}));

const evidence = {
  sku: 'SKU-A',
  status: 'observed',
  selected_model: 'ewma',
  history_points: 90,
  origins: 76,
  horizon: { kind: 'supplier_lead_time', days: 13, input_days: 12.2 },
  models: {
    seasonal_naive: { status: 'observed', horizon_units: 52, wape: 0.2, mase: 0.9, bias: -0.1 },
    ewma: { status: 'observed', horizon_units: 49, wape: 0.1, mase: 0.7, bias: 0.02 },
    croston_sba: { status: 'observed', horizon_units: 45, wape: 0.15, mase: 0.8, bias: 0.04 },
    tsb: { status: 'observed', horizon_units: 44, wape: 0.18, mase: 0.82, bias: 0.06 },
  },
  segmentation: { abc_class: 'A', abc_status: 'observed', xyz_class: 'Y', xyz_status: 'observed' },
  source: {
    kind: 'reconciled_active_purchase_facts',
    status: 'available',
    watermark: '2026-07-28',
  },
  authority: 'shadow_evaluation_only',
  can_increase_autonomy: false,
  materialized: false,
  computation_version: 'forecast_intelligence_v1',
};

describe('ForecastEvidence', () => {
  beforeEach(() => {
    vi.mocked(fetchInventoryForecast).mockResolvedValue(evidence as any);
    vi.mocked(materializeInventoryForecast).mockResolvedValue({
      ...evidence,
      materialized: true,
      evaluation_id: 'abcdef1234567890',
    } as any);
  });

  it('renders all model metrics, segmentation, horizon and authority', async () => {
    render(<ForecastEvidence sku="SKU-A" leadTimeDays={12.2} />);
    expect(await screen.findByTestId('forecast-model-ewma')).toHaveTextContent('selected');
    expect(screen.getByTestId('forecast-evidence')).toHaveTextContent('ABC A');
    expect(screen.getByTestId('forecast-evidence')).toHaveTextContent('XYZ Y');
    expect(screen.getByTestId('forecast-evidence')).toHaveTextContent('13-day supplier lead-time horizon');
    expect(screen.getByTestId('forecast-evidence')).toHaveTextContent('cannot increase autonomy');
    expect(screen.getByTestId('forecast-model-croston_sba')).toHaveTextContent('Croston/SBA');
  });

  it('seals the shadow evaluation without changing its authority', async () => {
    render(<ForecastEvidence sku="SKU-A" leadTimeDays={12.2} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Seal shadow evaluation' }));
    await waitFor(() => expect(materializeInventoryForecast).toHaveBeenCalledWith('SKU-A', 12.2));
    expect(await screen.findByRole('button', { name: 'Evaluation sealed' })).toBeDisabled();
    expect(screen.getByTestId('forecast-evidence')).toHaveTextContent('abcdef123456');
  });
});
