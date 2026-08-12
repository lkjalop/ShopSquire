export type TraceLeafTab =
  | 'summary' | 'events' | 'execution'
  | 'research' | 'why' | 'intent' | 'memory' | 'complexity'
  | 'evidence' | 'multimodal' | 'security'
  | 'market' | 'procurement'
  | 'audit' | 'raw';

export const TRACE_SECTIONS = [
  { id: 'decision', label: 'Decision', leaves: ['summary', 'events', 'execution'] },
  { id: 'research-fit', label: 'Research & Fit', leaves: ['research', 'why'] },
  { id: 'reasoning', label: 'Reasoning', leaves: ['intent', 'memory', 'complexity'] },
  { id: 'evidence-risk', label: 'Evidence & Risk', leaves: ['evidence', 'multimodal', 'security'] },
  { id: 'commercial', label: 'Commercial Journey', leaves: ['market', 'procurement'] },
  { id: 'audit-technical', label: 'Audit & Technical', leaves: ['audit', 'raw'] },
] as const satisfies ReadonlyArray<{
  id: string;
  label: string;
  leaves: readonly TraceLeafTab[];
}>;

export const TRACE_LEAF_LABELS: Record<TraceLeafTab, string> = {
  summary: 'Summary', events: 'Events', execution: 'Execution', research: 'Research Breakdown',
  why: 'Why', intent: 'Intent', memory: 'Memory', complexity: 'Complexity', evidence: 'Evidence',
  multimodal: 'Multimodal', security: 'Security', market: 'Market Intelligence',
  procurement: 'Procurement', audit: 'Audit Trail', raw: 'Raw',
};

export function traceSectionForLeaf(leaf: TraceLeafTab) {
  return TRACE_SECTIONS.find((section) => (
    (section.leaves as readonly TraceLeafTab[]).includes(leaf)
  )) || TRACE_SECTIONS[0];
}

export function normalizeTraceLeaf(value?: string): TraceLeafTab {
  const candidate = String(value || '').trim() as TraceLeafTab;
  return Object.prototype.hasOwnProperty.call(TRACE_LEAF_LABELS, candidate) ? candidate : 'events';
}
