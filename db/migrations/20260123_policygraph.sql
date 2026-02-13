-- PolicyGraph + ContextGraph schema (per-tenant). Optional; apply if needed.

-- ContextGraph nodes and edges
CREATE TABLE IF NOT EXISTS cg_nodes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    type TEXT NOT NULL,
    key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cg_nodes_tenant_type_key ON cg_nodes (tenant_id, type, key);

CREATE TABLE IF NOT EXISTS cg_edges (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    src_id TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    type TEXT NOT NULL,
    weight REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cg_edges_tenant_src_dst_type ON cg_edges (tenant_id, src_id, dst_id, type);

-- PolicyGraph policies, controls, rules, evaluations
CREATE TABLE IF NOT EXISTS pg_policies (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    framework TEXT NOT NULL,
    version TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pg_controls (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    control_key TEXT NOT NULL,
    description TEXT,
    severity TEXT DEFAULT 'medium',
    enabled INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_pg_controls_policy ON pg_controls (policy_id);

CREATE TABLE IF NOT EXISTS pg_rules (
    id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    rule TEXT NOT NULL,
    priority INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pg_rules_control ON pg_rules (control_id);

CREATE TABLE IF NOT EXISTS pg_evaluations (
    id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    result TEXT NOT NULL,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pg_evals_decision ON pg_evaluations (decision_id);

-- Optional Timescale hypertable for decision log timeseries (Postgres only)
-- CREATE EXTENSION IF NOT EXISTS timescaledb;
-- CREATE TABLE IF NOT EXISTS dl_timeseries (
--     time TIMESTAMP NOT NULL,
--     tenant_id TEXT,
--     agent_name TEXT,
--     status TEXT,
--     tags JSONB
-- );
-- SELECT create_hypertable('dl_timeseries','time', if_not_exists => TRUE);
