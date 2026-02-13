-- Search events for BI funnel tracking
CREATE TABLE IF NOT EXISTS search_events (
  id TEXT PRIMARY KEY,
  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
  uid_hash TEXT,
  query TEXT,
  filters_json TEXT,
  result_skus_json TEXT,
  result_count INTEGER,
  view_mode TEXT,
  trace_id TEXT,
  session_id TEXT
);
