export type AdminNavGroup = {
  id: string;
  label: string;
  items: readonly { id: string; label: string }[];
};

// Stable leaf ids preserve every existing ?tab= deep link.  The groups are a
// presentation boundary only; they do not change routing or API ownership.
export const ADMIN_NAV_GROUPS: readonly AdminNavGroup[] = [
  {
    id: 'command',
    label: 'Command',
    items: [
      { id: 'overview', label: 'Overview' },
      { id: 'merchant-bi', label: 'Business intelligence' },
      { id: 'orders', label: 'Orders' },
      { id: 'accounts', label: 'Accounts & parties' },
      { id: 'returns', label: 'Returns & repairs' },
    ],
  },
  {
    id: 'commerce',
    label: 'Commerce operations',
    items: [
      { id: 'procurement', label: 'Procurement' },
      { id: 'market-intel', label: 'Market intelligence' },
      { id: 'inventory-sync', label: 'Inventory sync' },
      { id: 'analytics', label: 'Evaluation & analytics' },
      { id: 'investor', label: 'Outcome metrics' },
    ],
  },
  {
    id: 'trust',
    label: 'Trust & safety',
    items: [
      { id: 'decisions', label: 'Decision traces' },
      { id: 'approvals', label: 'Approvals' },
      { id: 'security', label: 'Security' },
      { id: 'email-xdr', label: 'Email XDR' },
      { id: 'cv-incidents', label: 'Image incidents' },
      { id: 'email-incidents', label: 'Email incidents' },
      { id: 'incidents', label: 'Incidents' },
      { id: 'escalations', label: 'Escalations' },
    ],
  },
  {
    id: 'governance',
    label: 'Governance',
    items: [
      { id: 'compliance', label: 'Compliance' },
      { id: 'grc', label: 'Risk & controls' },
      { id: 'rules', label: 'Rules' },
      { id: 'playbooks', label: 'Playbooks' },
      { id: 'maestro', label: 'Agent boundaries' },
      { id: 'agent-intelligence', label: 'Agent intelligence' },
    ],
  },
  {
    id: 'platform',
    label: 'Platform evidence',
    items: [{ id: 'grafana', label: 'Operational dashboards' }],
  },
] as const;

export const ADMIN_NAV_LEAF_IDS = ADMIN_NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => item.id),
);
