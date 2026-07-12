-- LEGACY REFERENCE ONLY (not applied in production).
-- Source of truth is Alembic migrations in `alembic/` (run `alembic upgrade head`).
-- PostgreSQL schema for ShopSquire MVP

CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  phone TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  sku TEXT UNIQUE ON CONFLICT REPLACE NOT NULL,
  name TEXT NOT NULL,
  price_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  image_url TEXT,
  specs TEXT,
  active INTEGER DEFAULT 1,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  stock INT NOT NULL,
  warehouse TEXT DEFAULT 'default',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS draft_orders (
  id TEXT PRIMARY KEY,
  customer_id TEXT REFERENCES customers(id),
  tenant_id TEXT NOT NULL DEFAULT 'default',   -- R10.2: cart identity = (tenant_id, customer_id)
  line_items TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 0,          -- optimistic-concurrency token (P0.2 cart CAS)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  draft_order_id TEXT REFERENCES draft_orders(id),
  customer_id TEXT REFERENCES customers(id),
  guest_email TEXT,
  total_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'pending_payment',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  trace_id TEXT,
  decision_id TEXT
);

CREATE TABLE IF NOT EXISTS order_sessions (
  id TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Bi-temporal decision logs (simplified per PRD)
CREATE TABLE IF NOT EXISTS decision_logs (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  agent_session_id TEXT,
  user_id TEXT,
  tenant_id TEXT,
  valid_from TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  valid_to TEXT DEFAULT 'infinity',
  system_from TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  system_to TEXT DEFAULT 'infinity',
  input_data TEXT NOT NULL DEFAULT '{}',
  retrieved_context TEXT,
  agent_reasoning TEXT,
  proposed_action TEXT,
  evaluator_model TEXT,
  policy_version TEXT NOT NULL DEFAULT 'v1',
  approval_required INTEGER,
  approved_by TEXT,
  approved_at TEXT,
  execution_status TEXT,
  error_message TEXT,
  created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Decision lifecycle audits
CREATE TABLE IF NOT EXISTS decision_audits (
  id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor TEXT,
  metadata TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Optional: idempotency keys
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Security events (observer audit artifacts)
CREATE TABLE IF NOT EXISTS security_events (
  id TEXT PRIMARY KEY,
  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
  path TEXT,
  severity TEXT,
  verdict_score INT,
  details TEXT,
  escalated INTEGER DEFAULT 0,
  blocked INTEGER DEFAULT 0,
  ground_truth TEXT,
  analyst_verdict TEXT,
  correction_ts TEXT,
  correction_notes TEXT
);

CREATE TABLE IF NOT EXISTS iam_events (
  id TEXT PRIMARY KEY,
  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
  event_type TEXT,
  actor TEXT,
  source_ip TEXT,
  user_agent TEXT,
  success INTEGER DEFAULT 0,
  risk_score INT,
  details TEXT
);

-- Incidents created from security events or manual escalation
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  event_id TEXT REFERENCES security_events(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT,
  severity TEXT,
  title TEXT,
  description TEXT,
  status TEXT DEFAULT 'open'
);

-- RAGAS evaluation results (placeholder)
CREATE TABLE IF NOT EXISTS ragas_eval_results (
  eval_id TEXT PRIMARY KEY,
  decision_log_id TEXT REFERENCES decision_logs(id),
  faithfulness DECIMAL(3,2),
  answer_relevance DECIMAL(3,2),
  context_precision DECIMAL(3,2),
  context_recall DECIMAL(3,2),
  evaluated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  evaluator_model TEXT,
  created_at INTEGER DEFAULT (strftime('%s','now'))
);

-- Real-time decision trace events
CREATE TABLE IF NOT EXISTS decision_trace_events (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  trace_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT,
  target_type TEXT,
  target_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence_bundles (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  bundle_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Returns cases (product-agnostic: links SKU, evidence bundle, and decision trace)
CREATE TABLE IF NOT EXISTS return_cases (
  id TEXT PRIMARY KEY,
  tenant_id TEXT,
  uid TEXT,
  sku TEXT NOT NULL,
  vertical_pack_id TEXT,
  trace_id TEXT,
  evidence_id TEXT,
  decision_id TEXT,
  status TEXT DEFAULT 'open',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_return_cases_trace_id ON return_cases(trace_id);
CREATE INDEX IF NOT EXISTS idx_return_cases_sku ON return_cases(sku);

-- Human review queue tasks
CREATE TABLE IF NOT EXISTS human_review_tasks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT,
  case_id TEXT NOT NULL,
  trace_id TEXT,
  status TEXT DEFAULT 'pending',
  priority TEXT DEFAULT 'normal',
  reason TEXT,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_human_review_tasks_case_id ON human_review_tasks(case_id);

-- Auth/account tables (demo)
CREATE TABLE IF NOT EXISTS user_accounts (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token TEXT UNIQUE NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS payment_methods (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  label TEXT,
  brand TEXT,
  last4 TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oauth_identities (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  provider_user_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  email TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  return_to TEXT,
  expires_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
