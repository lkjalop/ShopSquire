import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import TurnHistoryPanel from '../TurnHistoryPanel';

it('selects persisted revisions without replacing their objective or authority', () => {
  render(<TurnHistoryPanel history={[
    { commit_id: 'old', known_at: '2026-01-02', valid_at: '2026-01-01', read_model: {case_revision: 2, operation_id: 'op-old', objective: 'Laptop', catalog_authority: 'blocked'} },
    { commit_id: 'new', known_at: '2026-02-02', valid_at: '2026-02-01', read_model: {case_revision: 3, operation_id: 'op-new', objective: 'Chair', buyer_query:'Make the budget 400', catalog_authority: 'permitted'} },
  ]} />);
  expect(screen.getByText('Case objective: Chair')).toBeVisible();
  expect(screen.getByText('Turn query: Make the budget 400')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Recorded turn revision'), {target:{value:'old'}});
  expect(screen.getByText('Case objective: Laptop')).toBeVisible();
  expect(screen.getByText('Turn query: not recorded')).toBeVisible();
  expect(screen.queryByText('Case objective: Chair')).toBeNull();
  expect(screen.queryByText('Turn query: Make the budget 400')).toBeNull();
  expect(screen.getByText(/op-old/)).toBeVisible();
  expect(screen.getByText(/blocked/)).toBeVisible();
});
