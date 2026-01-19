-- PostgreSQL schema for ShopSquire MVP

CREATE TABLE IF NOT EXISTS customers (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  phone TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
  id UUID PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  price_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  specs JSONB,
  active BOOLEAN DEFAULT TRUE,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory (
  id UUID PRIMARY KEY,
  product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  stock INT NOT NULL,
  warehouse TEXT DEFAULT 'default',
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS draft_orders (
  id UUID PRIMARY KEY,
  customer_id UUID REFERENCES customers(id),
  line_items JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
  id UUID PRIMARY KEY,
  draft_order_id UUID REFERENCES draft_orders(id),
  customer_id UUID REFERENCES customers(id),
  total_cents INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'pending_payment',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Bi-temporal decision logs (simplified per PRD)
CREATE TABLE IF NOT EXISTS decision_logs (
  id UUID PRIMARY KEY,
  agent_name TEXT NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL,
  valid_to TIMESTAMPTZ DEFAULT 'infinity',
  system_from TIMESTAMPTZ DEFAULT now(),
  system_to TIMESTAMPTZ DEFAULT 'infinity',
  input_data JSONB NOT NULL,
  retrieved_context JSONB,
  agent_reasoning TEXT,
  proposed_action JSONB,
  policy_version TEXT NOT NULL,
  approval_required BOOLEAN,
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  execution_status TEXT,
  error_message TEXT
);

-- Optional: idempotency keys
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Security events (observer audit artifacts)
CREATE TABLE IF NOT EXISTS security_events (
  id UUID PRIMARY KEY,
  event_time TIMESTAMPTZ DEFAULT now(),
  path TEXT,
  severity TEXT,
  verdict_score INT,
  details JSONB
);
