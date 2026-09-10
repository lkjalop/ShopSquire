/** Client ordering only: the server remains the owner of case revisions. */
export type TerminalIdentity = {
  operation_id?: string;
  case_id?: string | null;
  case_revision?: number | null;
};

export class TerminalInstallationGate {
  private generation = 0;
  private revisions = new Map<string, number>();
  begin(): number { return ++this.generation; }
  capture(): number { return this.generation; }
  isCurrent(token: number): boolean { return token === this.generation; }
  reset(): void { this.begin(); this.revisions.clear(); }
  accept(token: number, terminal: TerminalIdentity): boolean {
    if (!this.isCurrent(token) || !terminal.operation_id) return false;
    if (terminal.case_id) {
      const revision = terminal.case_revision;
      if (!Number.isInteger(revision) || Number(revision) < 1) return false;
      if (Number(revision) <= (this.revisions.get(terminal.case_id) ?? 0)) return false;
      this.revisions.set(terminal.case_id, Number(revision));
    }
    return true;
  }
}
