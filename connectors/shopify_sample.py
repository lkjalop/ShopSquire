"""Sample Shopify-like connector using the Tenant SDK.

Demonstrates registering webhooks and posting synthetic events to the platform.
"""
from sdk.tenant_sdk import BaseTenantConnector


def setup_shopify_connector(api_base: str, api_key: str, callback_url: str):
    connector = BaseTenantConnector(api_base=api_base, api_key=api_key)
    return connector.register_webhooks(callback_url)


def send_security_signal(api_base: str, api_key: str):
    connector = BaseTenantConnector(api_base=api_base, api_key=api_key)
    return connector.push_security_event(
        path="/shopify/webhook/order/create",
        details={"agent_event": {"interaction_type": "mcp.tool.invoked", "details": {"tool": "order.create"}}},
        severity="low",
    )
