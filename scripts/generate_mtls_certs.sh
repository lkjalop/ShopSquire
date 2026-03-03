#!/usr/bin/env bash
# C02 — Generate self-signed CA + service certificates for internal mTLS.
#
# Usage: bash scripts/generate_mtls_certs.sh [output_dir]
#
# Produces:
#   ca.key, ca.crt              — internal Certificate Authority
#   api.key, api.crt            — API service certificate
#   worker.key, worker.crt      — sync-worker/celery certificate
#   client.key, client.crt      — generic internal client certificate
#
# All certs are signed by the same CA so nginx can verify client certs.

set -euo pipefail

OUT="${1:-config/tls/certs}"
DAYS=365
CA_SUBJ="/CN=ShopSquire Internal CA/O=ShopSquire/C=US"

mkdir -p "$OUT"

echo "==> Generating CA key + certificate"
openssl genrsa -out "$OUT/ca.key" 4096
openssl req -new -x509 -key "$OUT/ca.key" -out "$OUT/ca.crt" \
  -days "$DAYS" -subj "$CA_SUBJ" -sha256

generate_service_cert() {
  local name="$1"
  local cn="$2"
  local san="${3:-DNS:$cn,DNS:localhost}"

  echo "==> Generating $name cert (CN=$cn)"
  openssl genrsa -out "$OUT/$name.key" 2048

  # CSR with SAN
  openssl req -new -key "$OUT/$name.key" -out "$OUT/$name.csr" \
    -subj "/CN=$cn/O=ShopSquire" \
    -addext "subjectAltName=$san"

  # Sign with CA
  openssl x509 -req -in "$OUT/$name.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
    -CAcreateserial -out "$OUT/$name.crt" -days "$DAYS" -sha256 \
    -extfile <(printf "subjectAltName=$san\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth,clientAuth")

  rm -f "$OUT/$name.csr"
  echo "    -> $OUT/$name.key, $OUT/$name.crt"
}

generate_service_cert "api"    "shopsquire-api"   "DNS:shopsquire-api,DNS:api,DNS:localhost,IP:127.0.0.1"
generate_service_cert "worker" "shopsquire-worker" "DNS:shopsquire-worker,DNS:worker,DNS:localhost"
generate_service_cert "client" "shopsquire-client" "DNS:shopsquire-client,DNS:client,DNS:localhost"

# Fingerprints for INTERNAL_MTLS_ALLOWED_FINGERPRINTS env var
echo ""
echo "=== Client certificate fingerprints (SHA-256) ==="
for cert in api worker client; do
  fp=$(openssl x509 -in "$OUT/$cert.crt" -noout -fingerprint -sha256 | sed 's/.*=//;s/://g' | tr '[:upper:]' '[:lower:]')
  echo "$cert: $fp"
done

echo ""
echo "Done. Mount $OUT into your containers and set:"
echo "  INTERNAL_MTLS_ALLOWED_FINGERPRINTS=<comma-separated fingerprints above>"
