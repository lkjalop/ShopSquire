import { describe, expect, it } from 'vitest';
import { ADMIN_NAV_GROUPS, ADMIN_NAV_LEAF_IDS } from './adminNavigation';

describe('admin navigation contract', () => {
  it('keeps every legacy merchant leaf reachable exactly once', () => {
    const legacyLeaves = [
      'merchant-bi', 'overview', 'decisions', 'security', 'maestro', 'email-xdr',
      'cv-incidents', 'inventory-sync', 'email-incidents', 'escalations', 'playbooks',
      'rules', 'approvals', 'accounts', 'procurement', 'market-intel', 'investor',
      'orders', 'analytics', 'grafana', 'incidents', 'compliance', 'grc',
      'agent-intelligence',
      'returns',
    ];

    expect([...ADMIN_NAV_LEAF_IDS].sort()).toEqual([...legacyLeaves].sort());
    expect(new Set(ADMIN_NAV_LEAF_IDS).size).toBe(legacyLeaves.length);
  });

  it('uses five operator-centred groups', () => {
    expect(ADMIN_NAV_GROUPS.map((group) => group.label)).toEqual([
      'Command', 'Commerce operations', 'Trust & safety', 'Governance', 'Platform evidence',
    ]);
  });
});
