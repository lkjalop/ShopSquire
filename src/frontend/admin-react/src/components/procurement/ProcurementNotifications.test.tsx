import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import ProcurementNotifications from './ProcurementNotifications';

vi.mock('../../api', () => ({ fcNotifications: vi.fn(), fcMarkNotificationsSeen: vi.fn() }));
import { fcNotifications, fcMarkNotificationsSeen } from '../../api';

describe('ProcurementNotifications', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the unseen badge + summaries and marks all seen', async () => {
    (fcNotifications as any).mockResolvedValue({
      unseen: 2,
      notifications: [
        { id: 'n1', kind: 'cases_materialized', summary: 'New cart confirmation: 2 sourcing case(s) created.' },
        { id: 'n2', kind: 'supplier_oob', summary: 'Supplier creatorfleet.example reported out_of_stock — 1 open case(s) affected.' },
      ],
    });
    (fcMarkNotificationsSeen as any).mockResolvedValue({ marked: 2 });
    const onActivity = vi.fn();
    render(<ProcurementNotifications onActivity={onActivity} pollMs={0} />);

    await waitFor(() => expect(screen.getByTestId('proc-notif-badge')).toHaveTextContent('2 new procurement updates'));
    expect(screen.getAllByTestId('proc-notif-item')).toHaveLength(2);
    expect(onActivity).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('proc-notif-seen'));
    await waitFor(() => expect(fcMarkNotificationsSeen).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('proc-notifications')).not.toBeInTheDocument());
  });

  it('renders nothing when there are no unseen notifications', async () => {
    (fcNotifications as any).mockResolvedValue({ unseen: 0, notifications: [] });
    render(<ProcurementNotifications pollMs={0} />);
    await waitFor(() => expect(fcNotifications).toHaveBeenCalled());
    expect(screen.queryByTestId('proc-notifications')).not.toBeInTheDocument();
  });

  it('refreshes the case queue only when the unseen count increases', async () => {
    vi.useFakeTimers();
    try {
      (fcNotifications as any)
        .mockResolvedValueOnce({ unseen: 2, notifications: [{ id: 'n1', summary: 'existing' }] })
        .mockResolvedValueOnce({ unseen: 2, notifications: [{ id: 'n1', summary: 'existing' }] })
        .mockResolvedValueOnce({
          unseen: 3,
          notifications: [{ id: 'n1', summary: 'existing' }, { id: 'n2', summary: 'new work' }],
        });
      const onActivity = vi.fn();
      render(<ProcurementNotifications onActivity={onActivity} pollMs={100} />);

      await act(async () => { await Promise.resolve(); });
      expect(fcNotifications).toHaveBeenCalledTimes(1);
      expect(onActivity).not.toHaveBeenCalled();

      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(fcNotifications).toHaveBeenCalledTimes(2);
      expect(onActivity).not.toHaveBeenCalled();

      await act(async () => { await vi.advanceTimersByTimeAsync(100); });
      expect(fcNotifications).toHaveBeenCalledTimes(3);
      expect(onActivity).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
