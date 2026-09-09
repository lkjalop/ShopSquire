import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import TurnHistoryPanel from '../TurnHistoryPanel';

it('selects persisted revisions without replacing their objective or authority', () => {
  render(<TurnHistoryPanel history={[
    { commit_id: 'old', known_at: '2026-01-02', valid_at: '2026-01-01', read_model: {case_revision: 2, operation_id: 'op-old', objective: 'Laptop', catalog_authority: 'blocked'} },
    { commit_id: 'new', known_at: '2026-02-02', valid_at: '2026-02-01', read_model: {case_revision: 3, operation_id: 'op-new', objective: 'Chair', catalog_authority: 'permitted'} },
  ]} />);
  expect(screen.getByText('Chair')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Recorded turn revision'), {target:{value:'old'}});
  expect(screen.getByText('Laptop')).toBeVisible();
  expect(screen.queryByText('Chair')).toBeNull();
  expect(screen.getByText(/op-old/)).toBeVisible();
  expect(screen.getByText(/blocked/)).toBeVisible();
});
