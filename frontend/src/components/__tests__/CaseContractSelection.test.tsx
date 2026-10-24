import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, vi, test, expect } from 'vitest';
import CaseContractSelection from '../CaseContractSelection';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test('failed requirement reads can be retried without changing the case', async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch'))
    .mockResolvedValueOnce({ok:true,json:async()=>({selection:{state:'unselected',case_revision:1},contracts:[]})});
  vi.stubGlobal('fetch', fetcher);
  render(<CaseContractSelection caseId="case" uid="buyer" />);
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button',{name:'Retry loading requirements'}));
  await screen.findByText('unselected');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls.every(([,options])=>!options.method)).toBe(true);
});

test('changing cases aborts the obsolete requirement read', async () => {
  const fetcher = vi.fn().mockImplementation(()=>new Promise(()=>{}));
  vi.stubGlobal('fetch', fetcher);
  const view = render(<CaseContractSelection caseId="first" uid="buyer" />);
  const first = fetcher.mock.calls[0][1].signal;
  view.rerender(<CaseContractSelection caseId="second" uid="buyer" />);
  expect(first.aborted).toBe(true);
  expect(fetcher.mock.calls[1][1].signal.aborted).toBe(false);
  view.unmount();
  expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true);
});

test('selection is explicit, revision bound, and revocable', async () => {
  const context = {subject:'Example',version:'1',platform:'Platform',workload:'Work'};
  const contract = {id:'contract',revision:'digest',context,obligations:[],exclusions:[]};
  let selection: any = {state:'unselected',case_revision:1};
  const fetcher = vi.fn(async (_url: any, options: any = {}) => {
    if (options.method === 'PUT') {
      expect(JSON.parse(options.body)).toMatchObject({expected_revision:1,contract_revision:'digest',context});
      selection = {state:'current',case_revision:2,binding_id:'bound'};
    }
    if (options.method === 'POST') selection = {state:'revoked',case_revision:3,binding_id:'bound'};
    return {ok:true,json:async()=>({selection,contracts:[contract]})};
  });
  vi.stubGlobal('fetch',fetcher);
  try {
    const onChange = vi.fn();
    render(<CaseContractSelection caseId="case" uid="buyer" onChange={onChange} />);
    await screen.findByText('unselected');
    expect(screen.getByRole('button',{name:'Select requirements'})).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Requirement scope'),{target:{value:'contract'}});
    fireEvent.click(screen.getByRole('button',{name:'Select requirements'}));
    await screen.findByText('current');
    fireEvent.click(screen.getByRole('button',{name:'Revoke selection'}));
    await waitFor(()=>expect(screen.getByText('revoked')).toBeInTheDocument());
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({state:'revoked',case_revision:3}));
  } finally { vi.unstubAllGlobals(); }
});
