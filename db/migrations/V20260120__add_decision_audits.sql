-- Migration: Add decision_audits table for lifecycle audit trail
CREATE TABLE IF NOT EXISTS decision_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id UUID NOT NULL,
    action TEXT NOT NULL,
    actor TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decision_audits_decision_id ON decision_audits(decision_id);
