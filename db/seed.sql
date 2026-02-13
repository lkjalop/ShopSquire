-- Minimal seed data
INSERT INTO products (id, sku, name, price_cents, currency, specs, active)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'LAPTOP_DELL_XPS_13', 'Dell XPS 13', 89900, 'USD', '{"ram":"16GB","ssd":"512GB"}', 1)
ON CONFLICT DO NOTHING;

INSERT INTO inventory (id, product_id, stock, warehouse)
VALUES ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 12, 'default')
ON CONFLICT DO NOTHING;
