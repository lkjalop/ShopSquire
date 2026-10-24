import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import BuyerSupplierQuotes from '../BuyerSupplierQuotes';

afterEach(()=>vi.unstubAllGlobals());

it('requires explicit selection of the displayed terms and keeps uncovered units visible',async()=>{
  const quote={quote_id:'reply',sku:'SKU',quantity:10,uncovered_quantity:5,coverage:'partial',eligible:true,
    currency:'AUD',total_price_cents:1012000,freight_cents:12000,covered_order_quantity:25,
    covered_order_total_price_cents:2512000,minimum_order:1,estimated_lead_days:5,
    expires_at:'2026-10-06',selection_digest:'a'.repeat(64)};
  const fetcher=vi.fn(async(url:string,options?:RequestInit)=>({ok:true,json:async()=>
    options?.method==='POST'?{status:'current',selection_id:'selection',quote}:
    url.includes('/supplier-quotes?')?{status:'reviewed_options',case_revision:2,quotes:[quote]}:{status:'unselected'}}));
  vi.stubGlobal('fetch',fetcher);
  render(<BuyerSupplierQuotes caseId="case" uid="buyer" revision={2} tenantId="shop"/>);
  const button=await screen.findByRole('button',{name:'Select this sourcing estimate'});
  expect(screen.getByText(/Remaining shortfall: 5/)).toBeVisible();
  expect(screen.getByText(/Uncovered units are excluded/)).toBeVisible();
  expect(fetcher.mock.calls.every(([,options])=>options?.method!=='POST')).toBe(true);
  fireEvent.click(button);
  await screen.findByText(/Sourcing estimate selected for operator review/);
  const submission=fetcher.mock.calls.find(([,options])=>options?.method==='POST')!;
  expect(JSON.parse(String(submission[1]?.body))).toEqual({uid:'buyer',expected_revision:2,
    quote_id:'reply',expected_digest:'a'.repeat(64)});
  expect(button).toBeDisabled();
});

it('shows stale selection truthfully and never silently reaccepts it',async()=>{
  const fetcher=vi.fn(async(url:string)=>({ok:true,json:async()=>url.includes('/supplier-quotes?')?
    {status:'reviewed_options',case_revision:3,quotes:[]}:{status:'revalidation_required'}}));
  vi.stubGlobal('fetch',fetcher);
  render(<BuyerSupplierQuotes caseId="case" uid="buyer" revision={3}/>);
  await waitFor(()=>expect(screen.getByText(/previous selection is no longer current/)).toBeVisible());
  expect(screen.queryByRole('button',{name:'Select this sourcing estimate'})).toBeNull();
});

it('shows a deadline conflict without offering selection',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url.includes('/supplier-quotes?')?
    {status:'reviewed_options',case_revision:2,quotes:[{quote_id:'late',sku:'SKU',quantity:15,
      eligible:false,reason:'estimated_delivery_after_deadline',estimated_lead_days:5,
      requirement_assessment:{deadline_status:'estimate_late',budget_status:'not_requested',
        required_by:'2026-10-07T00:00:00Z'}}]}:{status:'unselected'}})));
  render(<BuyerSupplierQuotes caseId="case" uid="buyer" revision={2}/>);
  expect(await screen.findByText(/Estimated arrival misses your recorded deadline/)).toBeVisible();
  expect(screen.queryByRole('button',{name:'Select this sourcing estimate'})).toBeNull();
});
