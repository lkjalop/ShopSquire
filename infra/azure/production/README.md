# ShopSquire production Azure profile

This profile is the hardened alternative to `infra/azure/main.bicep`, which
remains the lower-cost portfolio/pilot composition. It creates:

- three-subnet VNet: separate edge and core Container Apps infrastructure plus
  a private-endpoint data subnet;
- one shared NAT Gateway and static egress IP;
- separate zone-redundant, internal edge and core Container Apps environments;
- Front Door Premium, WAF managed/bot rules, a global rate bound, private origin
  and CDN caching limited to `/assets/*`;
- private PostgreSQL 16 Flexible Server with optional zone-redundant HA and an
  opt-in asynchronous read replica and explicit read-only application boundary;
- private, highly available Azure Managed Redis with queue-depth worker scaling;
- private Key Vault, Blob evidence storage and Premium Container Registry;
- managed-identity return-evidence custody using private Blob storage and a
  versioned Key Vault envelope key (`return-evidence-key-v1`);
- private DNS, managed-identity access to secrets/evidence/registry, Application
  Insights, Log Analytics, cost budget and initial PostgreSQL alerts;
- bounded migration execution and post-deployment topology validation.

## Important authentication boundary

The runtime identity accesses Key Vault, Blob and ACR without account keys. The
current SQLAlchemy and Celery clients do not yet refresh PostgreSQL and Redis
Entra tokens, so this profile generates their transitional credentials once,
stores connection secrets in Key Vault and passes only Key Vault references to
the applications. It does **not** accept database or Redis URLs as deployment
parameters. Do not describe this as passwordless data-plane authentication.

The generated bootstrap bundle is DPAPI-protected for the current Windows user
and machine. Preserve it in an approved secret backup; losing it blocks safe,
idempotent updates. CI deployments should supply an equivalent protected bundle
from an authorized secret store.

## Before deployment

1. Run `az login` and select a subscription with Owner or equivalent resource
   and role-assignment rights.
2. Ensure the chosen region supports three availability zones, PostgreSQL
   zone-redundant HA, Azure Managed Redis `Balanced_B0`, Container Apps zone
   redundancy, and Front Door Private Link.
3. Make the supplied OCI image references pullable by Azure. The template also
   provisions a private ACR for the durable image path, but a first deployment
   may use immutable public GHCR digests. Never deploy mutable `latest` tags.
4. Confirm the monthly budget, notification email and expected NAT egress IP
   allow-list process.
5. Expect managed data and Private Link provisioning to take tens of minutes.

## Deploy

```powershell
./infra/azure/production/deploy-production.ps1 `
  -SubscriptionId '<subscription-id>' `
  -ResourceGroup 'rg-shopsquire-prod-aue' `
  -Location 'australiaeast' `
  -Prefix 'shopsquire-prod' `
  -BackendImage 'ghcr.io/<owner>/shopsquire-api@sha256:<digest>' `
  -WebImage 'ghcr.io/<owner>/shopsquire-web@sha256:<digest>' `
  -OwnerEmail 'operations@example.com' `
  -MonthlyBudgetAmount 1500
```

The deployer performs Bicep compilation, provider registration, a what-if,
deployment, Front Door private-link approval, core private-DNS completion,
migration execution and an edge health check. Add `-EnableReadReplica` only when
the application has a measured replica-safe read workload; it is not required
for HA. Use `-WhatIf` for PowerShell command preview or `-SkipWhatIf` only in a
pre-reviewed automated pipeline.

Validate independently:

```powershell
./infra/azure/production/validate-production.ps1 `
  -SubscriptionId '<subscription-id>' `
  -ResourceGroup 'rg-shopsquire-prod-aue'
```

## Release gates

Do not send real customer traffic until all are retained as artifacts:

- Bicep build and Azure what-if;
- successful deployment and private-link approval;
- successful Alembic execution;
- `validate-production.ps1` output;
- production-shaped browser/security battery;
- database restore drill from [RECOVERY.md](RECOVERY.md);
- WAF false-positive review and verified prevention-mode browser/security smoke;
- measured load envelope proving replica, database connection and queue limits.

Payment execution and autonomous supplier sending remain disabled by the
template. Enabling either is a separate tenant-scoped policy decision, not a
deployment side effect.

Return evidence is encrypted by the application before it reaches Blob storage.
Rotate it by adding a new `return-evidence-key-vN` secret, retaining prior keys
for evidence still inside retention/legal-hold windows, and updating
`RETURN_EVIDENCE_ACTIVE_KEY_ID` plus `RETURN_EVIDENCE_KEY_IDS`. Removing an old
key before its evidence has expired makes that evidence intentionally unreadable.

## FinOps defaults

- The read replica is off; HA is on.
- Web/API replicas start at two and scale horizontally to ten.
- Workers scale from one to ten against the Celery queue depth.
- Front Door caches immutable assets only.
- PostgreSQL starts at `Standard_D2ds_v5`; scale vertically only after sustained
  CPU, memory, I/O and query evidence.
- Budget alerts fire at 75% actual and 100% forecast.
- Development should use the pilot profile or a separate reduced parameter set;
  do not leave this full topology running as an idle demo environment.
