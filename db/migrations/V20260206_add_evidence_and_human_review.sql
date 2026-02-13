-- Migration: Add evidence_bundles and human_review_tasks tables
-- Generated: 2026-02-06

CREATE TABLE IF NOT EXISTS evidence_bundles (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  bundle_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS human_review_tasks (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  decision_id TEXT,
  ticket_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer_id TEXT,
  rationale TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP
);

-- Index for lookups by case_id
CREATE INDEX IF NOT EXISTS idx_evidence_bundles_case_id ON evidence_bundles(case_id);
CREATE INDEX IF NOT EXISTS idx_human_review_tasks_case_id ON human_review_tasks(case_id);
