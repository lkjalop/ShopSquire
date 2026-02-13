CREATE TABLE IF NOT EXISTS order_sessions (
  id UUID PRIMARY KEY,
  uid TEXT NOT NULL,
  order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_sessions_uid_created_at ON order_sessions (uid, created_at DESC);
