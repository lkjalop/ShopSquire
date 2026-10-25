# start_demo.ps1 — launch the ShopSquire backend for a LIVE DEMO.
# Runtime model + flag overrides only (does NOT modify your .env). Run this in your own terminal so the
# server persists for the whole demo:   ./start_demo.ps1
#
# Text roles use the shared runtime profile; vision stays on the VL model (so image queries
# still work via the configured qwen3-vl:8b). Demo replay on; market-intel shown in the decision trace (shadow).

. (Join-Path $PSScriptRoot 'scripts/local_demo_runtime.ps1')
. (Join-Path $PSScriptRoot 'scripts/assert_local_ollama.ps1')
Set-Location $PSScriptRoot
python scripts/bootstrap_demo_runtime.py --seed
if ($LASTEXITCODE -ne 0) { throw "Demo database bootstrap failed" }

. (Join-Path $PSScriptRoot 'scripts/enroll_local_demo_models.ps1')
# Start Ollama through scripts/start_local_ollama.ps1 so server limits match this profile.

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
$env:MULTI_INTENT_LLM_MODEL            = $demoProfile.text_model   # the resident model — no swap latency
$env:MULTI_INTENT_LLM_TIMEOUT_SEC      = "30"
# LLM planner fallback (R1 2026-07-07): low-confidence decompositions ("something quiet for my
# startup") escalate to ONE schema-forced LLM call that fills the gaps (profile-vocab clamped,
# never overrides a rule extraction). Also carries image identity so "like this but cheaper" works.
$env:LLM_PLANNER_ENABLED               = "1"
$env:LLM_PLANNER_TIMEOUT_SEC           = "20"    # bounded planner deadline
$env:OLLAMA_KEEP_ALIVE                 = "2m"    # pin generate/vision models resident (P0 lever)
# Vision's bounded cold-load allowance comes from the shared runtime profile.
$env:CV_DAMAGE_REASONING_TIMEOUT_S     = "8"      # only runs when damage evidence exists
$env:CV_DEEP_OCR_TIMEOUT_S             = "6"      # risk-triggered OCR cannot hold the request open
$env:CV_VISUAL_SEARCH_OCR_FALLBACK     = "0"      # VLM already extracts text; deep OCR is risk-triggered
$env:CV_SELECTIVE_OCR_PROVIDER         = "tesseract" # CPU fallback only for QR/overlay risk evidence
$env:CV_SELECTIVE_OCR_TIMEOUT_S        = "3"      # bounded before the deeper OCR ladder
# Model residency is serialized by the shared Ollama server profile. Keep the text router and
# taxonomy embedder warm for the main journey; selective IMAGE V2 loads vision only on demand.
# Record image acts last, or expect the following text turn to pay one router reload.
$env:CV_WARMUP_ON_START                = "0"
$env:VLM_WARMUP_ON_START               = "0"      # do not evict the text router after its blocking prewarm
# Serve the bounded V2 core for its eligible recommendation lanes. The procurement switch below
# enrolls only read-only product selection and sourcing advice; fulfillment_cases still owns case
# creation, RFQ drafts, approvals, and all external sends. Unsupported lanes continue to delegate,
# and cart mutations remain confirmation-gated because auto-apply is intentionally disabled.
$env:SHOPSQUIRE_RUNTIME_PROFILE        = "demo_v2"
$env:RECOMMEND_CORE_MODE               = "primary"
$env:RECOMMEND_PROCUREMENT_ADVICE_MODE = "on"
$env:RECOMMEND_POLICY_ANSWER_MODE      = "on" # approved StoreProfile FAQ only; never model-authored terms
$env:RECOMMEND_SUPPORT_HANDOFF_MODE    = "on" # advice only; case submission remains domain-owned
$env:RECOMMEND_INVENTORY_READ_MODE     = "on" # read only; reorder actions remain authorization-gated
$env:RECOMMEND_LEGACY_DELEGATE_ENABLED = "0"  # explicit V2 pilot: unsupported lanes fail boundedly
$env:RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED = "1" # chat uses typed facade outcomes, never direct suggest()
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
# Evidence orchestrator (N1): plan-selected legs (market/policy/availability/history/image) feed the
# Evidence tab + source chips. Legs are bounded (2.5s) and additive — message text is untouched.
$env:EVIDENCE_ORCHESTRATOR_ENABLED     = "1"
$env:EVIDENCE_LEG_BUDGET_SEC           = "2.5"
# Named game requirements use the Steam storefront only after the shopper explicitly consents.
# The connector is source-allowlisted, title-matched, response-bounded and fail-closed.
$env:STEAM_REQUIREMENTS_LIVE_ENABLED   = "1"
# Supplier comms stay SAFE for the demo (no real email): sandbox transport + autonomy OFF.
$env:FULFILLMENT_SUPPLIER_TRANSPORT = "sandbox"
$env:FULFILLMENT_AUTONOMOUS_RFQ     = "0"

# A previous image turn may leave the VLM resident across backend restarts. Free that slot before
# startup so the router prewarm can establish the configured text-model profile.
ollama stop $env:CV_VISION_MODEL 2>$null | Out-Null

# An occupied port does not establish ownership of the existing process.
if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Backend port 8080 is occupied. Stop the intended backend before launching the demo.'
}

Write-Host "Starting ShopSquire backend on http://127.0.0.1:8080 ($env:ROUTER_MODEL, demo mode)..." -ForegroundColor Green
Write-Host "Bootstrapping the demo sold taxonomy..." -ForegroundColor Cyan
python scripts/bootstrap_sold_taxonomy.py
if ($LASTEXITCODE -ne 0) { throw "Demo sold-taxonomy bootstrap failed" }
python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8080
