import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import RawTracePanel from '../decision-trace/RawTracePanel';

const classes = { muted: 'muted', sectionTitle: 'title', rawJson: 'raw' };

describe('RawTracePanel', () => {
  it('labels a missing snapshot and preserves normalized events without inference', () => {
    render(<RawTracePanel trace={null} events={[{ event_type: 'human_joined' }]} traceId="trace-1" replay={null} replayLoading={false} classNames={classes} />);
    expect(screen.getByText(/snapshot_status/)).toHaveTextContent('unavailable');
    expect(screen.getByText(/snapshot_status/)).toHaveTextContent('human_joined');
  });
});
