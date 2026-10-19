/** Client ordering only: the server remains the owner of case revisions. */
export type TerminalIdentity = {
  operation_id?: string;
  case_id?: string | null;
  case_revision?: number | null;
  read_only_case_task?: boolean;
};

export class TerminalInstallationGate {
  private generation = 0;
  private revisions = new Map<string, number>();
  private operations = new Map<string, string>();
  begin(): number { return ++this.generation; }
  capture(): number { return this.generation; }
  isCurrent(token: number): boolean { return token === this.generation; }
  reset(): void { this.begin(); this.revisions.clear(); this.operations.clear(); }
  accept(token: number, terminal: TerminalIdentity): boolean {
    if (!this.isCurrent(token) || !terminal.operation_id) return false;
    if (terminal.case_id) {
      const revision = terminal.case_revision;
      if (!Number.isInteger(revision) || Number(revision) < 1) return false;
      const prior = this.revisions.get(terminal.case_id) ?? 0;
      if (Number(revision) < prior || (Number(revision) === prior && !terminal.read_only_case_task)) return false;
      if (this.operations.get(terminal.case_id) === terminal.operation_id) return false;
      this.revisions.set(terminal.case_id, Number(revision));
      this.operations.set(terminal.case_id, terminal.operation_id);
    }
    return true;
  }
}
