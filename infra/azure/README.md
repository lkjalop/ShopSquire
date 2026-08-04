# ShopSquire Azure deployment

> This file describes the economical pilot profile. For the private,
> zone-redundant production composition, use
> [`production/README.md`](production/README.md). The profiles are intentionally
> separate so a demonstration does not silently provision production HA cost.

This directory deploys the portable ShopSquire runtime contract to Azure
Container Apps. It is intentionally a composition layer: the application still
depends on standard OCI, PostgreSQL, Redis, HTTP/OTLP, object-storage and secret
contracts rather than Azure services inside domain logic.

## What the template creates

- public same-origin web gateway containing the storefront and `/admin/` UI;
- internal API with separate `/healthz` and `/readyz` probes;
- one Celery worker and one Redis-leased scheduler;
- a manually triggered, single-owner Alembic migration job;
- Log Analytics-backed Container Apps environment;
- user-assigned managed identity and Key Vault secret references;
- private evidence container with public access disabled;
- an unlocked time-based Blob immutability policy (lock only after retention/legal approval);
- conservative HTTP concurrency scaling and database pool bounds.

The first template deliberately accepts PostgreSQL and Redis URLs. This permits
either Azure managed data services or portable providers without maintaining two
application manifests. A production tenant should use Azure Database for
PostgreSQL Flexible Server and Azure Managed Redis with private endpoints. A
portfolio deployment may use an existing compatible managed service.

## Prerequisites

1. An Azure subscription and permission to create role assignments.
2. Azure CLI with the Container Apps extension and Bicep CLI.
3. Two registry images visible to Azure: `Dockerfile` and `Dockerfile.web`.
   The `Publish cloud images` GitHub workflow produces SBOM/provenance-enabled
   GHCR images. Make the selected packages public or add a private-registry
   identity before deploying them.
4. PostgreSQL 16 and authenticated TLS Redis endpoints.
5. The PostgreSQL `vector` extension allowed/created before migrations when
   vector retrieval is enabled.

## Deploy

```powershell
az login

$db = Read-Host 'PostgreSQL SQLAlchemy URL' -AsSecureString
$redis = Read-Host 'Redis TLS URL (rediss://...)' -AsSecureString

./infra/azure/deploy.ps1 `
  -SubscriptionId '<subscription-id>' `
  -ResourceGroup 'rg-shopsquire-demo' `
  -Location 'australiaeast' `
  -BackendImage 'ghcr.io/<owner>/shopsquire-api:sha-<commit>' `
  -WebImage 'ghcr.io/<owner>/shopsquire-web:sha-<commit>' `
  -DatabaseUrl $db `
  -RedisUrl $redis
```

Confirm the migration execution succeeds before treating `/readyz` or browser
smoke results as release evidence. Keep the image digest, Bicep deployment ID,
migration execution, browser report and rollback revision as the proof bundle.

The evidence immutability policy is intentionally deployed **unlocked**. Test
retention and privacy-deletion behavior first. Locking a policy is operationally
consequential and should be a separately approved production action.

The deployment generates non-default merchant, owner and developer API keys and
stores them in Key Vault. Retrieve the owner key only when opening the operator
UI; do not bake it into `VITE_*`, image layers, source control or browser local
storage. Replacing these bootstrap keys with Entra-backed operator identity is a
pilot-hardening task.

## Cloud-native versus cloud-portable

| Concern | Portable contract | Azure composition |
|---|---|---|
| Compute | OCI API/web/worker/scheduler/job | Container Apps and Container Apps Job |
| Database | PostgreSQL 16 + Alembic | PostgreSQL Flexible Server |
| Queue/cache | authenticated TLS Redis | Azure Managed Redis |
| Secrets | provider-neutral references | Key Vault + managed identity |
| Evidence | object storage adapter | private Blob container |
| Telemetry | structured logs, Prometheus, OTLP | Log Analytics; optional ACA managed OTel agent/App Insights |
| Edge | trusted reverse-proxy contract | optional Front Door Premium/WAF |
| Models | versioned model-provider contract | optional Microsoft Foundry endpoint |

The Azure-native option reduces operational burden and improves identity,
networking and threat-intelligence integration. The portable option reduces
lock-in and supports AWS, GCP, sovereign clouds or customer infrastructure. The
trade-off is that portable deployments must assemble their own WAF, secret
rotation, immutable storage, alert routing and managed database operations.

## Concurrency envelope

The pilot defaults are deliberately bounded:

- API: 1–3 replicas, scale target 20 concurrent HTTP requests per replica;
- Uvicorn: one process per replica; slow model/narration work must remain bounded
  or move to the worker;
- worker: one replica with concurrency 2;
- scheduler: exactly one replica plus a renewable Redis lease;
- database: set `DB_POOL_SIZE=5` and `DB_POOL_MAX_OVERFLOW=5` per process.

Do not advertise a concurrent-user number from replica count. Measure three
traffic mixes separately: short deterministic reads, recommendation turns with
model narration, and consequential procurement operations. Gate scale changes
on p95/p99 latency, error/timeout rate, database connections, queue age and cost
per completed journey. Add replicas before adding Uvicorn processes so each
container has a predictable failure and memory boundary.

## Client IP, GeoIP and ASN security

`X-Forwarded-For` is never trusted from a direct peer. The application validates
the immediate peer against `TRUSTED_PROXY_CIDRS`, walks the chain right-to-left,
and stores only an IP hash with country/ASN/provider-health metadata in the
security decision. Azure Container Apps appends the sender on the right; earlier
values can be attacker supplied.

GeoIP/ASN is a signal, not identity and not a standalone deny rule:

- local MaxMind MMDB and version metadata are preferred;
- external IP lookup is disabled unless `GEOIP_ALLOW_NETWORK_LOOKUP=1`;
- lookup failure is recorded as `unavailable`, not silently converted to low risk;
- high-risk hosting/VPN/ASN observations can request MFA/challenge or operator
  review, but payment/procurement denial requires corroborating evidence;
- raw IP retention must be separately justified. IP hashes still require a
  retention/deletion policy because linkability can make them personal data.

Prometheus alerts cover forwarding-header spoof attempts, enrichment-source
failure, high-risk ASN bursts and repeated-actor velocity. For an internet-facing
pilot, place Azure Front Door Premium/WAF ahead of the web app, restrict origin
access to Front Door, start managed rules in detection mode, then promote tuned
rules to prevention. Send Front Door access/WAF logs and application security
events to the same tenant-scoped incident timeline, using request/trace IDs—not
raw IP alone—for correlation.

## Honest claims

After a successful deployment and smoke run, it is fair to say:

> Deployed ShopSquire on Azure Container Apps with managed identity, Key Vault,
> isolated API/worker/scheduler/migration workloads, trusted-proxy IP handling,
> and rollback-ready revisions.

Do not yet claim Azure production certification, proven business lift,
multi-region resilience, or autonomous procurement at scale. Those require a
restore drill, load envelope, WAF/incident exercise, tenant-authorized shadow
data and measured outcomes.

## References

- [Azure Container Apps ingress headers](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview)
- [Azure Container Apps scaling](https://learn.microsoft.com/en-us/azure/container-apps/scale-app)
- [Container Apps Key Vault references](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets)
- [Container Apps managed OpenTelemetry agent](https://learn.microsoft.com/en-us/azure/container-apps/opentelemetry-agents)
- [Azure Front Door security guidance](https://learn.microsoft.com/en-us/azure/frontdoor/secure-front-door)
- [Azure WAF capabilities](https://learn.microsoft.com/en-us/azure/frontdoor/web-application-firewall)
- [PostgreSQL pgvector](https://learn.microsoft.com/en-us/azure/postgresql/extensions/how-to-use-pgvector)
