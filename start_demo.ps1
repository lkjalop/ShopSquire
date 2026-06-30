# start_demo.ps1 — launch the ShopSquire backend for a LIVE DEMO.
# Runtime model + flag overrides only (does NOT modify your .env). Run this in your own terminal so the
# server persists for the whole demo:   ./start_demo.ps1
#
# Text reasoning/narration on qwen3:14b; vision stays on the VL model (14b is text-only, so image queries
# still work via the configured qwen3-vl:8b). Demo replay on; market-intel shown in the decision trace (shadow).

$env:OLLAMA_DEFAULT_MODEL      = "qwen3:14b"
$env:OLLAMA_SMALL_MODEL        = "qwen3:14b"     # recommendation/procurement narration uses 14b (was 8b-vl)
$env:OLLAMA_SUMMARY_MODEL      = "qwen3:14b"
# vision/CV/security/OCR intentionally left as configured (qwen3-vl:8b / glm-ocr / llama-guard3)

$env:FULFILLMENT_DEMO_ENABLED          = "1"      # enables replay Reset/Advance + demo supplier reply
$env:FULFILLMENT_AUTO_DRAFT_ON_COMMIT  = "1"      # a confirmed cart auto-drafts the supplier RFQ (email body to show)
$env:HIPPOGRAPH_FEEDBACK_ENABLED       = "shadow" # market-intel appears in the decision trace, does NOT steer the buyer
# Supplier comms stay SAFE for the demo (no real email): sandbox transport + autonomy OFF.
$env:FULFILLMENT_SUPPLIER_TRANSPORT = "sandbox"
$env:FULFILLMENT_AUTONOMOUS_RFQ     = "0"

# free port 8080 if a stale backend is still running
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Write-Host "Starting ShopSquire backend on http://127.0.0.1:8080 (qwen3:14b, demo mode)..." -ForegroundColor Green
python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8080
