-- Core tables for Postgres deployments

CREATE SCHEMA IF NOT EXISTS oltp;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS security;

SET search_path TO oltp, audit, security, public;

-- Decision logs (bitemporal)
CREATE TABLE IF NOT EXISTS audit.decision_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_name TEXT NOT NULL,
  valid_from TIMESTAMPTZ DEFAULT now(),
  valid_to TIMESTAMPTZ DEFAULT 'infinity',
  system_from TIMESTAMPTZ DEFAULT now(),
  system_to TIMESTAMPTZ DEFAULT 'infinity',
  input_data JSONB,
  retrieved_context JSONB,
  agent_reasoning TEXT,
  proposed_action JSONB,
  policy_version TEXT,
  approval_required BOOLEAN,
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  execution_status TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS audit.decision_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id UUID NOT NULL,
  action TEXT NOT NULL,
  actor TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- CV analyses
CREATE TABLE IF NOT EXISTS oltp.cv_analyses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id TEXT NOT NULL,
  image_sha256 TEXT,
  image_phash TEXT,
  damage_type TEXT,
  damage_location TEXT,
  severity TEXT,
  confidence DOUBLE PRECISION,
  serial_number TEXT,
  extracted_text TEXT,
  raw_labels JSONB,
  model_version TEXT,
  processing_time_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Fraud image hashes
CREATE TABLE IF NOT EXISTS security.fraud_image_hashes (
  phash TEXT PRIMARY KEY,
  first_seen_case_id TEXT,
  times_seen INTEGER DEFAULT 1,
  confirmed_fraud BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Cases
CREATE TABLE IF NOT EXISTS oltp.cases (
  id TEXT PRIMARY KEY,
  order_id TEXT,
  customer_id TEXT,
  guest_email TEXT,
  issue_type TEXT,
  description TEXT,
  status TEXT DEFAULT 'open',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Return labels
CREATE TABLE IF NOT EXISTS oltp.return_labels (
  id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL,
  carrier TEXT NOT NULL,
  tracking_number TEXT NOT NULL,
  label_url TEXT NOT NULL,
  status TEXT DEFAULT 'generated',
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ,
  shipped_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ
);

-- Orders (subset for demo)
CREATE TABLE IF NOT EXISTS oltp.orders (
  id TEXT PRIMARY KEY,
  draft_order_id TEXT,
  customer_id TEXT,
  guest_email TEXT,
  serial_number TEXT,
  total_cents INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'pending_payment',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Serial mapping
CREATE TABLE IF NOT EXISTS oltp.order_serials (
  order_id TEXT PRIMARY KEY,
  serial TEXT
);
