-- Migration: Add tickets table for approval workflow

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    external_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT,
    status TEXT NOT NULL,
    approval_required BOOLEAN DEFAULT FALSE,
    trace_id TEXT,
    tenant_id TEXT,
    evidence JSON DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_trace_id ON tickets(trace_id);

-- Trigger to update updated_at on row modification (Postgres syntax)
CREATE OR REPLACE FUNCTION tickets_updated_at_trigger()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tickets_updated_at ON tickets;
CREATE TRIGGER trg_tickets_updated_at
BEFORE UPDATE ON tickets
FOR EACH ROW EXECUTE FUNCTION tickets_updated_at_trigger();
