-- Enable TimescaleDB extension for this database.
-- This runs automatically on first container init (fresh volume) when using docker-compose.timescaledb.yml.
CREATE EXTENSION IF NOT EXISTS timescaledb;

