import { describe, it, expect } from 'vitest';
import { buildFulfilmentResolution, type CombinedAvailability } from '../fulfilmentResolution';

const base: CombinedAvailability = {
  sku: 'LAP-1',
  requested: 20,
  local_now: 10,
  network_transfer: 5,
  transfer_plan: [{ from_location: 'WH-2', qty: 5 }],
  supplier_rfq_qty: 5,
  fillable_from_network: false,
  supplier_availability: 'unconfirmed_rfq',
};

describe('buildFulfilmentResolution', () => {
  it('returns null when the network fully covers demand (no decision to surface)', () => {
    const full: CombinedAvailability = {
      ...base, requested: 10, local_now: 10, network_transfer: 0,
      transfer_plan: [], supplier_rfq_qty: 0, fillable_from_network: true,
    };
    expect(buildFulfilmentResolution(full, { productName: 'X' })).toBeNull();
  });

  it('offers source_shortfall + change_requirement, but NOT mixed_alternative without alternatives', () => {
    const r = buildFulfilmentResolution(base, { productName: 'Asus TUF' })!;
    expect(r.options).toEqual(['source_shortfall', 'change_requirement']);
    expect(r.supplier_rfq_qty).toBe(5);
  });

  it('adds mixed_alternative only when a shortfall AND alternatives both exist', () => {
    const r = buildFulfilmentResolution(base, {
      productName: 'Asus TUF',
      alternatives: [{ sku: 'LAP-2', name: 'Lenovo LOQ' }],
    })!;
    expect(r.options).toContain('mixed_alternative');
  });

  it('never claims supplier stock is confirmed', () => {
    const r = buildFulfilmentResolution(base, { productName: 'Asus TUF' })!;
    expect(r.supplier_confirmed).toBe(false);
  });

  it('drops zero-qty transfer legs', () => {
    const r = buildFulfilmentResolution(
      { ...base, transfer_plan: [{ from_location: 'WH-2', qty: 5 }, { from_location: 'WH-3', qty: 0 }] },
      { productName: 'X' })!;
    expect(r.transfer_plan).toHaveLength(1);
    expect(r.transfer_plan[0].from_location).toBe('WH-2');
  });
});
