# start_demo.ps1 — launch the ShopSquire backend for a LIVE DEMO.
# Runtime model + flag overrides only (does NOT modify your .env). Run this in your own terminal so the
# server persists for the whole demo:   ./start_demo.ps1
#
# Text reasoning/narration on qwen3:14b; vision stays on the VL model (14b is text-only, so image queries
# still work via the configured qwen3-vl:8b). Demo replay on; market-intel shown in the decision trace (shadow).

$env:OLLAMA_DEFAULT_MODEL      = "qwen3:14b"
$env:OLLAMA_SMALL_MODEL        = "qwen3:14b"     # recommendation/procurement narration uses 14b (was 8b-vl)
$env:OLLAMA_SUMMARY_MODEL      = "qwen3:14b"
$env:OLLAMA_EMBED_KEEP_ALIVE   = "60m"           # pin nomic-embed resident (reload costs 2.8-6.1s when evicted)
# NOTE (Ollama SERVER config, set where `ollama serve` runs — not here): to stop embeds queuing
# behind 14b generations, set OLLAMA_NUM_PARALLEL=2 and OLLAMA_MAX_LOADED_MODELS=3 in the Ollama
# service environment, then restart Ollama. App-side keep_alive above only prevents the reload.
# vision/CV/security/OCR intentionally left as configured (qwen3-vl:8b / glm-ocr / llama-guard3)

$env:FULFILLMENT_DEMO_ENABLED          = "1"      # enables replay Reset/Advance + demo supplier reply
$env:FULFILLMENT_AUTO_DRAFT_ON_COMMIT  = "1"      # a confirmed cart auto-drafts the supplier RFQ (email body to show)
$env:HIPPOGRAPH_FEEDBACK_ENABLED       = "shadow" # market-intel appears in the decision trace, does NOT steer the buyer
$env:MARKET_PIPELINE_ENABLED           = "1"      # operator "Refresh live data" runs the REAL market pipeline
$env:COMMERCE_CATALOG_ENABLED          = "1"      # price_book joins power competitor-undercut findings
# Multi-intent orchestration (amendments/mixed orders in chat): deterministic grammar FIRST, then the
# schema-constrained local-LLM binding for phrasings the regex misses ("get rid of the HP and reduce the
# IdeaPad to 20"). Without these the planner is DEAD and cart commands fall through to product search.
$env:MULTI_INTENT_PLANNER_ENABLED      = "1"
$env:MULTI_INTENT_LLM_BINDING_ENABLED  = "1"
$env:MULTI_INTENT_LLM_MODEL            = "qwen3:14b"   # the resident model — no swap latency
$env:MULTI_INTENT_LLM_TIMEOUT_SEC      = "30"
# LLM planner fallback (R1 2026-07-07): low-confidence decompositions ("something quiet for my
# startup") escalate to ONE schema-forced LLM call that fills the gaps (profile-vocab clamped,
# never overrides a rule extraction). Also carries image identity so "like this but cheaper" works.
$env:LLM_PLANNER_ENABLED               = "1"
$env:LLM_PLANNER_TIMEOUT_SEC           = "20"    # qwen3:14b measures 4-7s on planner prompts
$env:OLLAMA_KEEP_ALIVE                 = "30m"    # pin generate/vision models resident (P0 lever)
# Evidence orchestrator (N1): plan-selected legs (market/policy/availability/history/image) feed the
# Evidence tab + source chips. Legs are bounded (2.5s) and additive — message text is untouched.
$env:EVIDENCE_ORCHESTRATOR_ENABLED     = "1"
$env:EVIDENCE_LEG_BUDGET_SEC           = "2.5"
# Supplier comms stay SAFE for the demo (no real email): sandbox transport + autonomy OFF.
$env:FULFILLMENT_SUPPLIER_TRANSPORT = "sandbox"
$env:FULFILLMENT_AUTONOMOUS_RFQ     = "0"

# free port 8080 if a stale backend is still running
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Write-Host "Starting ShopSquire backend on http://127.0.0.1:8080 (qwen3:14b, demo mode)..." -ForegroundColor Green
Write-Host "Bootstrapping the demo sold taxonomy..." -ForegroundColor Cyan
python scripts/bootstrap_sold_taxonomy.py
if ($LASTEXITCODE -ne 0) { throw "Demo sold-taxonomy bootstrap failed" }
python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8080
