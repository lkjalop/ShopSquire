.PHONY: integration up down test-integration

up:
	docker-compose up -d --remove-orphans

down:
	docker-compose down

wait-db:
	@echo "Waiting for Postgres to be ready..."
	@sleep 5

test-integration: up wait-db
	@echo "Running integration tests..."
	pytest -q tests/integration || (echo "Tests failed"; make down; exit 1)

.PHONY: test-determinism

# Determinism gate: the recommend route suite in FILE ORDER — which is the adversarial
# Apple→ASUS ordering (the image-brand cross-test contamination that the stale catalog-brands
# cache caused). Run together with the grounding/stage parity suites so a regression in the
# cache-invalidation / autouse-reset isolation is caught here, not by a flaky CI shuffle.
# NOTE: true multi-order randomization needs `pytest-randomly` (NOT currently a dependency —
# adding it will likely surface further order-dependent tests repo-wide; tracked as follow-up).
test-determinism:
	@echo "Determinism gate — recommend route suite (file order = Apple→ASUS adversarial)"
	python -m pytest tests/test_recommend.py tests/services/test_grounding_ladder.py \
	  tests/services/test_recommend_utils.py tests/services/test_recommend_budget_advisor.py \
	  tests/services/test_recommend_nqe_stage.py tests/test_no_flavour_in_core.py -p no:randomly -q

.PHONY: bench

# Latency baseline for the recommend route (p50/p95 per timing_breakdown stage). Capture BEFORE
# any latency-improvement change (trace batching, narration skip), then re-run and compare.
# Needs a running stack (default http://localhost:8080). Override: make bench URL=... N=...
bench:
	python scripts/bench_recommend.py --url $(or $(URL),http://localhost:8080) --n $(or $(N),20)

.PHONY: playwright-install playwright-smoke

playwright-install:
	@echo "Installing Playwright browsers (Chromium)"
	python -m playwright install chromium

playwright-smoke:
	@echo "Running Playwright smoke tests (storefront/product/widget)"
	python -m pytest -q tests/playwright
