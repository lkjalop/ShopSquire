# Ingress JA3/JA4 Wiring

ShopSquire app middleware consumes trusted `X-JA3-Hash` and `X-JA4-Hash`.
True JA3/JA4 extraction must happen at edge ingress.

## Production pattern

1. Edge proxy generates JA3/JA4 from TLS ClientHello.
2. Edge sets `X-JA3-Hash` and `X-JA4-Hash` on upstream request.
3. Internal mTLS/ingress proxy forwards those headers unchanged.
4. App trusts only known proxy CIDRs and drops spoofed header sources.

## Included templates

- Envoy edge: `config/tls/envoy-ja3-ja4-edge.yaml`
- Nginx edge (module-based extraction): `config/tls/nginx-edge-ja3-ja4.conf`
- Internal forwarding tier: `config/tls/nginx-mtls.conf`

## Envoy edge

Use `envoy.filters.listener.tls_inspector` and add JA3/JA4 values as request headers.
Exact dynamic metadata keys depend on your Envoy extension build.
Replace placeholder metadata keys in the template with the keys from your deployment.

## Nginx edge

Stock Nginx does not expose JA3/JA4 variables.
Use an Nginx build/module that exposes JA3/JA4 variables, then map them to:

- `X-JA3-Hash`
- `X-JA4-Hash`

The sample config assumes `$ja3_hash` and `$ja4_hash`.
If your module uses different variable names, update those directives.

## App trust and fail-closed

Set and enforce:

- `TLS_FINGERPRINT_ENABLED=1`
- `TLS_FINGERPRINT_TRUST_FAIL_CLOSED=1`
- `TLS_FINGERPRINT_TRUSTED_PROXY_CIDRS=<edge/internal ingress CIDRs only>`

Also ensure app pods are not directly internet-reachable when header trust is enabled.

## Validation checklist

1. Send real TLS traffic through edge ingress.
2. Verify upstream request carries `X-JA3-Hash` and `X-JA4-Hash`.
3. Confirm app traces include `ja3_hash`, `ja4_hash`, and `trusted_proxy_source=true`.
4. Send direct pod traffic with spoofed headers and confirm hashes are ignored.
