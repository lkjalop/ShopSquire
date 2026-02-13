# Tenant SDK

Purpose: provide a simple, consistent way for client platforms (Shopify/Magento/etc.) to integrate with the agentic platform via webhooks and REST.

## Quick Start
```python
from connectors.shopify_sample import setup_shopify_connector, send_security_signal

api_base = "http://localhost:8080"
api_key = "local-merchant-key"
callback_url = "https://example.com/webhooks/shopsquire"

print(setup_shopify_connector(api_base, api_key, callback_url))
print(send_security_signal(api_base, api_key))
```

## Operations
- Register webhooks for order/cart changes
- Push security events for tool invocations or anomalies
- Future: ingest decisions, approvals, and incidents directly

## Canary Rollout
- Use per-tenant feature flags and rollout percent to enable capabilities gradually.
- Track event delivery via `event_log` outbox; retry on failures.
