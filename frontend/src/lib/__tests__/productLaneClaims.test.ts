import {describe,expect,it} from 'vitest';
import {laneForProduct,laneTitle,laneSummary} from '../productLanes';

describe('product display grouping conveys observed identity, not invented fit',()=>{
  it.each(['27 inch Computer Monitor','Laptop Bag','External Hard Drive','Apple M1 Mac mini','Generic Laptop'])('%s is not assigned an unobserved operating system',name=>{
    expect(laneForProduct({name,price:100} as any)).toBe('catalogue');
  });
  it.each([
    ['Windows 11 Laptop','windows'],['MacBook Air','macbook'],['Chromebook','tablet_chromebook'],
  ])('retains the explicit product identity %s',(name,lane)=>{
    expect(laneForProduct({name,price:100} as any)).toBe(lane);
  });
  it('uses a category-neutral title for unclassified products',()=>{
    expect(laneTitle('catalogue' as any)).toBe('Catalogue options');
  });
  it('does not infer use-case fit or battery reliability from a group',()=>{
    const summary=laneSummary('macbook',[{name:'MacBook Air',price:100,currency:'AUD'}] as any,'high','software development');
    expect(summary).not.toMatch(/prioritized for battery|reliability|use-case fit|performance-oriented/);
    expect(summary).toMatch(/snapshot/i);
    expect(summary).toMatch(/verif/i);
  });
  it('retains mixed-currency comparison uncertainty',()=>{
    const summary=laneSummary('windows',[
      {name:'Windows Laptop',price:100,currency:'USD'},
      {name:'Windows Laptop',price:100,currency:'EUR'},
    ] as any);
    expect(summary).toMatch(/conversion required/);
  });
  it('does not manufacture zero prices for missing observations',()=>{
    const summary=laneSummary('windows',[{name:'Windows Laptop',currency:'AUD'}] as any);
    expect(summary).toMatch(/price.*(?:unknown|unavailable|not available)/i);
    expect(summary).not.toContain('0.00');
  });
  it('does not silently replace an invalid observed currency with USD',()=>{
    const summary=laneSummary('windows',[{name:'Windows Laptop',price:100,currency:'invalid'}] as any);
    expect(summary).toMatch(/currency unknown/i);
    expect(summary).not.toContain('USD');
  });
  it('can group a malformed optional feature observation without throwing',()=>{
    expect(laneForProduct({name:'Monitor',features:{}} as any)).toBe('catalogue');
  });
});
