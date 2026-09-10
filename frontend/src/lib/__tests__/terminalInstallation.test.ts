import { describe, expect, it } from 'vitest';
import { TerminalInstallationGate } from '../terminalInstallation';

describe('terminal installation ordering', () => {
  const terminal = (revision: number, op = `op-${revision}`) => ({
    operation_id: op, case_id: 'case', case_revision: revision,
  });
  it('rejects an older request even when it finishes last with a higher revision', async () => {
    const gate = new TerminalInstallationGate();
    const old = gate.begin();
    const current = gate.begin();
    expect(gate.accept(current, terminal(2))).toBe(true);
    await Promise.resolve();
    expect(gate.accept(old, terminal(9))).toBe(false);
    expect(gate.isCurrent(old)).toBe(false);
  });
  it('rejects revision regression, conflicting same-revision operations and duplicates', () => {
    const gate = new TerminalInstallationGate();
    expect(gate.accept(gate.begin(), terminal(3))).toBe(true);
    expect(gate.accept(gate.begin(), terminal(2))).toBe(false);
    expect(gate.accept(gate.begin(), terminal(3, 'different'))).toBe(false);
    expect(gate.accept(gate.begin(), terminal(3))).toBe(false);
    expect(gate.accept(gate.begin(), terminal(4))).toBe(true);
  });
  it('invalidates completion and errors after conversation reset', () => {
    const gate = new TerminalInstallationGate();
    const token = gate.begin();
    gate.reset();
    expect(gate.accept(token, terminal(1))).toBe(false);
    expect(gate.isCurrent(token)).toBe(false);
  });
});
