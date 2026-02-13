-- SQLite-friendly migration for tickets table (local dev)

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    external_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT,
    status TEXT NOT NULL,
    approval_required INTEGER DEFAULT 0,
    trace_id TEXT,
    tenant_id TEXT,
    evidence TEXT DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_trace_id ON tickets(trace_id);

-- Note: SQLite does not support the same trigger/function syntax used for Postgres.
-- Keeping updated_at in sync can be handled in application code or with a simple
-- update during writes in tests/dev.
