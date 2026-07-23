# start_demo.ps1 — launch the ShopSquire backend for a LIVE DEMO.
# Runtime model + flag overrides only (does NOT modify your .env). Run this in your own terminal so the
# server persists for the whole demo:   ./start_demo.ps1
#
# Text reasoning/narration on qwen3:14b; vision stays on the VL model (14b is text-only, so image queries
# still work via the configured qwen3-vl:8b). Demo replay on; market-intel shown in the decision trace (shadow).

$env:OLLAMA_DEFAULT_MODEL      = "qwen3:14b"
$env:OLLAMA_SMALL_MODEL        = "qwen3:14b"     # recommendation/procurement narration uses 14b (was 8b-vl)
$env:OLLAMA_SUMMARY_MODEL      = "qwen3:14b"
$env:ROUTER_MODEL              = "qwen3:14b"     # V2 router ignores generic OLLAMA_* model aliases
$env:CLASSIFIER_MODEL          = "qwen3:14b"     # taxonomy/onboarding text classification
$env:OLLAMA_VISION_MODEL       = "qwen3-vl:8b"
$env:CV_VISION_MODEL           = "qwen3-vl:8b"
$env:CV_MODEL                  = "qwen3-vl:8b"
$env:OLLAMA_EMBED_KEEP_ALIVE   = "60m"           # pin nomic-embed resident (reload costs 2.8-6.1s when evicted)
# NOTE (Ollama SERVER config, set where `ollama serve` runs — not here): to stop embeds queuing
# behind 14b generations, set OLLAMA_NUM_PARALLEL=2 and OLLAMA_MAX_LOADED_MODELS=2 in the Ollama
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
$env:CV_VISION_TIMEOUT_SEC             = "8"      # per-call network/model bound
$env:CV_PROVIDER_TOTAL_TIMEOUT_S       = "10"     # whole identity leg, including fallback
$env:CV_DAMAGE_REASONING_TIMEOUT_S     = "8"      # only runs when damage evidence exists
$env:CV_DEEP_OCR_TIMEOUT_S             = "6"      # risk-triggered OCR cannot hold the request open
$env:CV_VISUAL_SEARCH_OCR_FALLBACK     = "0"      # VLM already extracts text; deep OCR is risk-triggered
$env:CV_SELECTIVE_OCR_PROVIDER         = "tesseract" # CPU fallback only for QR/overlay risk evidence
$env:CV_SELECTIVE_OCR_TIMEOUT_S        = "3"      # bounded before the deeper OCR ladder
# A 12GB GPU cannot keep qwen3:14b and qwen3-vl:8b resident together. Keep the text router and
# taxonomy embedder warm for the main journey; selective IMAGE V2 loads vision only on demand.
# Record image acts last, or expect the following text turn to pay one router reload.
$env:CV_WARMUP_ON_START                = "0"
# Serve the bounded V2 core for its eligible recommendation lanes. The procurement switch below
# enrolls only read-only product selection and sourcing advice; fulfillment_cases still owns case
# creation, RFQ drafts, approvals, and all external sends. Unsupported lanes continue to delegate,
# and cart mutations remain confirmation-gated because auto-apply is intentionally disabled.
$env:RECOMMEND_CORE_MODE               = "primary"
$env:RECOMMEND_PROCUREMENT_ADVICE_MODE = "on"
$env:RECOMMEND_POLICY_ANSWER_MODE      = "on" # approved StoreProfile FAQ only; never model-authored terms
$env:ROUTER_PREWARM_ON_START           = "1"
$env:ROUTER_PREWARM_BLOCKING           = "1"
$env:ROUTER_PREWARM_REQUIRED           = "1"
$env:RECOMMEND_CART_SERVE              = "1"
# Preserve quota enforcement in the demo, but allow a full recorded journey for one guest. The
# production limits remain sourced from the deployment environment and are intentionally lower.
$env:TOKEN_BUDGET_ENABLED              = "1"
$env:TOKEN_BUDGET_GUEST_DAILY_TOKENS   = "100000"
$env:TOKEN_BUDGET_GUEST_DAILY_USD      = "10"
# URL guard is fail-closed. Explicitly authorize only the local Ollama endpoints used by this demo;
# without this, a normal launcher restart silently downgrades image identity to the filename fallback.
$env:INTERNAL_SERVICE_ALLOWLIST        = "127.0.0.1:11434,localhost:11434"
# Evidence orchestrator (N1): plan-selected legs (market/policy/availability/history/image) feed the
# Evidence tab + source chips. Legs are bounded (2.5s) and additive — message text is untouched.
$env:EVIDENCE_ORCHESTRATOR_ENABLED     = "1"
$env:EVIDENCE_LEG_BUDGET_SEC           = "2.5"
# Supplier comms stay SAFE for the demo (no real email): sandbox transport + autonomy OFF.
$env:FULFILLMENT_SUPPLIER_TRANSPORT = "sandbox"
$env:FULFILLMENT_AUTONOMOUS_RFQ     = "0"

# A previous image turn may leave the VLM resident across backend restarts. Free that slot before
# startup so the router prewarm can establish the intended qwen3:14b + nomic demo profile.
ollama stop $env:CV_VISION_MODEL 2>$null | Out-Null

# free port 8080 if a stale backend is still running
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Write-Host "Starting ShopSquire backend on http://127.0.0.1:8080 (qwen3:14b, demo mode)..." -ForegroundColor Green
Write-Host "Bootstrapping the demo sold taxonomy..." -ForegroundColor Cyan
python scripts/bootstrap_sold_taxonomy.py
if ($LASTEXITCODE -ne 0) { throw "Demo sold-taxonomy bootstrap failed" }
python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8080
