-- TimescaleDB hypertables for ShopSquire (requires TimescaleDB extension enabled)

-- decision_logs hypertable on valid_from
SELECT create_hypertable('decision_logs', 'valid_from', if_not_exists => TRUE);

-- security_events hypertable on event_time
SELECT create_hypertable('security_events', 'event_time', if_not_exists => TRUE);

