import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import MarketIntelligencePanel from '../decision-trace/MarketIntelligencePanel';


const classNames = { summaryPane: 'pane', sectionTitle: 'title', empty: 'empty', kvRow: 'row' };
const humanize = (value: unknown) => String(value ?? 'unknown').replaceAll('_', ' ');


describe('MarketIntelligencePanel evidence truth', () => {
  it('does not render missing inventory or bulk observations as zero', () => {
    render(<MarketIntelligencePanel
      classNames={classNames}
      humanize={humanize}
      formatTime={(value) => String(value)}
      events={[{ payload: {
        sku: 'SKU-1', rank: 1, demand_trend: 'insufficient_data',
        forecast_units_30d: null, stock_on_hand: null, velocity_dsi_days: null,
        bulk_frequency: null, bulk_frequency_state: 'not_collected',
        status: 'insufficient_data', source_status: { sales: 'insufficient_data', inventory: 'not_disclosed' },
      } }]}
    />);
    expect(screen.getByText(/not disclosed on hand/i)).toBeInTheDocument();
    expect(screen.getByText('not collected')).toBeInTheDocument();
    expect(screen.queryByText(/0 cases/)).not.toBeInTheDocument();
  });
});
