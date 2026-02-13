-- LEGACY REFERENCE ONLY (not applied in production).
-- Source of truth is Alembic migrations in `alembic/` (run `alembic upgrade head`).
-- Postgres-only schema segregation and pgvector extension

-- Set search_path for this session so unqualified names resolve to these schemas first
SET search_path TO oltp, audit, security, public;

-- Create schemas if they do not exist
CREATE SCHEMA IF NOT EXISTS oltp;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS security;

-- Enable pgvector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- OLTP tables
CREATE TABLE IF NOT EXISTS oltp.customers (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  phone TEXT,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.products (
  id TEXT PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  price_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  image_url TEXT,
  specs JSONB,
  active BOOLEAN DEFAULT TRUE,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.inventory (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES oltp.products(id) ON DELETE CASCADE,
  stock INT NOT NULL,
  warehouse TEXT DEFAULT 'default',
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.draft_orders (
  id TEXT PRIMARY KEY,
  customer_id TEXT REFERENCES oltp.customers(id),
  line_items JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.orders (
  id TEXT PRIMARY KEY,
  draft_order_id TEXT REFERENCES oltp.draft_orders(id),
  customer_id TEXT REFERENCES oltp.customers(id),
  guest_email TEXT,
  total_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'pending_payment',
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oltp.order_sessions (
  id TEXT PRIMARY KEY,
  uid TEXT NOT NULL,
  order_id TEXT NOT NULL REFERENCES oltp.orders(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- pgvector embeddings for products (dimension can be adjusted)
CREATE TABLE IF NOT EXISTS oltp.product_embeddings (
  product_id TEXT PRIMARY KEY REFERENCES oltp.products(id) ON DELETE CASCADE,
  embedding vector(1536),
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- AUDIT tables (bitemporal)
CREATE TABLE IF NOT EXISTS audit.decision_logs (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  agent_session_id TEXT,
  user_id TEXT,
  tenant_id TEXT,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  valid_to TIMESTAMPTZ,
  system_from TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  system_to TIMESTAMPTZ,
  input_data JSONB NOT NULL,
  retrieved_context JSONB,
  agent_reasoning JSONB,
  proposed_action JSONB,
  evaluator_model TEXT,
  policy_version TEXT NOT NULL,
  approval_required BOOLEAN,
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  execution_status TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit.decision_audits (
  id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES audit.decision_logs(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  actor TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- RAGAS evaluation results
CREATE TABLE IF NOT EXISTS audit.ragas_eval_results (
  eval_id TEXT PRIMARY KEY,
  decision_log_id TEXT REFERENCES audit.decision_logs(id),
  faithfulness DOUBLE PRECISION,
  answer_relevance DOUBLE PRECISION,
  context_precision DOUBLE PRECISION,
  context_recall DOUBLE PRECISION,
  evaluated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  evaluator_model TEXT,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit.evidence_bundles (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  bundle_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- SECURITY tables
CREATE TABLE IF NOT EXISTS security.security_events (
  id TEXT PRIMARY KEY,
  event_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  path TEXT,
  severity TEXT,
  verdict_score INT,
  details JSONB,
  escalated BOOLEAN DEFAULT FALSE,
  blocked BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS security.iam_events (
  id TEXT PRIMARY KEY,
  event_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  event_type TEXT,
  actor TEXT,
  source_ip TEXT,
  user_agent TEXT,
  success BOOLEAN DEFAULT FALSE,
  risk_score INT,
  details JSONB
);

CREATE TABLE IF NOT EXISTS security.incidents (
  id TEXT PRIMARY KEY,
  event_id TEXT REFERENCES security.security_events(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  created_by TEXT,
  severity TEXT,
  title TEXT,
  description TEXT,
  status TEXT DEFAULT 'open'
);

-- Optional helper: set default search_path for role used in tests
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shopsquire') THEN
    EXECUTE 'ALTER ROLE shopsquire SET search_path = oltp, audit, security, public';
  END IF;
END$$;
