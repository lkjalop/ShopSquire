CREATE TABLE IF NOT EXISTS evidence_bundles (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  bundle_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
