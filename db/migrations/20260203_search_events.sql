-- Search event tracking scaffold

CREATE TABLE IF NOT EXISTS search_events (
    id TEXT PRIMARY KEY,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT,
    query TEXT,
    query_cluster_id TEXT,
    viewed_sku TEXT,
    added_to_cart INTEGER DEFAULT 0,
    purchased INTEGER DEFAULT 0
);
