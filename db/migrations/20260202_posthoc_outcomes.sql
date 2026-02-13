CREATE TABLE IF NOT EXISTS posthoc_outcomes (
  id TEXT PRIMARY KEY,
  decision_id TEXT,
  outcome_type TEXT,
  outcome_value TEXT,
  evidence_json TEXT,
  valid_from TEXT,
  valid_to TEXT,
  system_from TEXT,
  system_to TEXT,
  actor_id TEXT,
  actor_role TEXT
);
