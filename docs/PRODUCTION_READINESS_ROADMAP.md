# Production Readiness Roadmap

## Modularity & Client Integration
- Plugin registry: `src/app/services/registry.py` with `config/plugins.yml`; load at startup.
- Standardize agent/tool contracts (request/response, tracing hooks, calibration, HEC emit).

## Scale & Reliability
- Migrate to Postgres + TimescaleDB; use Alembic migrations and `/api/v1/admin/db/ensure-timescale`.
- Background jobs via Redis/Celery or async TaskGroups for forensics/RAGAS/clustering.

## Security & Compliance
- Externalize secrets to cloud secret managers; rotate via API key endpoints in `admin.py`.
- JWT/OIDC for admin/merchant; audit changes; DLP enforcement; verify data retention and encryption.

## ML Governance
- Drift dashboards and nightly batch evaluation; alerts on regressions; A/B model selection with feature flags.

## CI/CD & Quality
- Expand Playwright coverage for trace popup and escalation room; WS/SSE load tests.
- Static checks (bandit, mypy, ruff), SBOM/dependency review.
- Deployment manifests (Docker, Helm, Terraform), K8s HPA/PDB, canary rollouts.
