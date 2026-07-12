# start_cart_validation.ps1 — start the demo backend with the V2 CART LANE served live.
# Wraps start_demo.ps1 (all the demo env + uvicorn) and adds ONLY the cart-lane flag.
# Does NOT modify your .env or start_demo.ps1. Run in YOUR OWN terminal so it persists:
#     ./start_cart_validation.ps1
#
# RECOMMEND_CART_SERVE=on  -> a natural-language cart edit that the frontend regex MISSES
# (compound edits like "get rid of the HP and reduce the IdeaPad to 20") is served by the
# grounded cart lane: resolve -> risk-tier -> confirmation card -> transactional apply.
# Parallel-run: the frontend regex is still first-chance; the backend only sees the misses.
# Search lanes stay LEGACY (RECOMMEND_CORE_MODE untouched = off). Text model = qwen3:14b.

$env:RECOMMEND_CART_SERVE = "on"
& "$PSScriptRoot\start_demo.ps1"
