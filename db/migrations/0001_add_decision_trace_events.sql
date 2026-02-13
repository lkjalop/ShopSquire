-- Migration: add decision_trace_events table

CREATE TABLE IF NOT EXISTS decision_trace_events (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT,
  target_type TEXT,
  target_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
