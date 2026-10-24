import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import SupplierEnquiryPanel from '../SupplierEnquiryPanel';

vi.mock('../../lib/csrf', () => ({apiFetch:vi.fn()}));
import {apiFetch} from '../../lib/csrf';
afterEach(() => { cleanup(); vi.clearAllMocks(); });

test('an approver can read the exact recipient, subject and body before approval', async () => {
  vi.mocked(apiFetch).mockResolvedValue({id:'enquiry', status:'pending', delivery_status:'not_dispatched',
    requested_quantity:40,shortfall:26,sku:'SKU',case_revision:4,value_cents:4000000,currency:'AUD',
    approval_state:'not_requested',quotes:[],message:{recipient:'quotes@fixture.invalid',
      subject:'Stock shortfall enquiry',body:'Please quote 26 units of SKU. No purchase is authorized.'}});
  render(<SupplierEnquiryPanel />);
  fireEvent.change(screen.getByLabelText('Supplier tenant'),{target:{value:'shop'}});
  fireEvent.change(screen.getByLabelText('Enquiry ID'),{target:{value:'enquiry'}});
  fireEvent.click(screen.getByRole('button',{name:'Load enquiry'}));
  expect(await screen.findByText('quotes@fixture.invalid')).toBeVisible();
  expect(screen.getByText('Stock shortfall enquiry')).toBeVisible();
  expect(screen.getByText('Please quote 26 units of SKU. No purchase is authorized.')).toBeVisible();
  expect(screen.getByRole('button',{name:'Approve enquiry'})).toBeEnabled();
  expect(apiFetch).toHaveBeenCalledTimes(1);
});

test('loading a budget-redacted draft preserves the saved disclosure choice', async () => {
  vi.mocked(apiFetch).mockResolvedValue({id:'enquiry', status:'pending', delivery_status:'not_dispatched',
    requested_quantity:40,shortfall:26,sku:'SKU',case_revision:4,value_cents:4000000,currency:'AUD',
    approval_state:'not_requested',quotes:[],draft_version:2,draft_artifact:{include_budget:false},
    message:{recipient:'quotes@fixture.invalid',subject:'Stock shortfall enquiry',body:'Quote 26 units.'}});
  render(<SupplierEnquiryPanel />);
  fireEvent.change(screen.getByLabelText('Supplier tenant'),{target:{value:'shop'}});
  fireEvent.change(screen.getByLabelText('Enquiry ID'),{target:{value:'enquiry'}});
  fireEvent.click(screen.getByRole('button',{name:'Load enquiry'}));
  expect(await screen.findByLabelText('Include buyer budget in supplier message')).not.toBeChecked();
  expect(screen.getByRole('button',{name:'Save revised draft for review'})).toBeDisabled();
  expect(screen.getByText('Draft version 2. Changes require fresh independent approval.')).toBeVisible();
});
