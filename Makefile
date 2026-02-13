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

.PHONY: playwright-install playwright-smoke

playwright-install:
	@echo "Installing Playwright browsers (Chromium)"
	python -m playwright install chromium

playwright-smoke:
	@echo "Running Playwright smoke tests (storefront/product/widget)"
	python -m pytest -q tests/playwright
