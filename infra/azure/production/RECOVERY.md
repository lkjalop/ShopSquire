# ShopSquire Azure recovery runbook

This runbook is deliberately separate from normal scaling. A read replica is
not a backup, and a healthy deployment does not prove recoverability.

## Recovery objectives to approve

- transactional PostgreSQL: target RPO 0 for an availability-zone failure,
  target RTO 15 minutes including application validation;
- regional database disaster: initial target RPO 5 minutes and RTO 60 minutes;
- Redis: rebuildable cache and queue state; durable job intent remains in
  PostgreSQL, so loss must not authorize or duplicate consequential actions;
- immutable evidence: restore by version into a new account/container; never
  overwrite the source during a drill;
- application: redeploy pinned image digests and the same Bicep revision.

These are engineering targets until timed drills demonstrate them.

## Quarterly PostgreSQL restore drill

1. Record the deployment ID, primary server, migration head, recovery timestamp
   and current application image digests.
2. Restore PostgreSQL to a new isolated server from a point at least 30 minutes
   earlier. Never restore over the production server.
3. Attach the restored server only to an isolated validation environment.
4. Run Alembic current/head validation, tenant-isolation checks, ledger
   conservation checks and representative read-only journeys.
5. Measure data loss against the requested timestamp and total recovery time.
6. Destroy the isolated copy only after the proof bundle is retained and the
   exact resource IDs are independently reviewed.

## Availability-zone incident

1. Confirm Azure PostgreSQL HA state and Container Apps replica health.
2. Freeze migrations and consequential outbound execution; do not disable
   storefront reads unnecessarily.
3. Observe automatic database failover. Do not promote an asynchronous read
   replica for an ordinary zonal incident.
4. Validate `/readyz`, transaction writes, tenant RLS context, queue lease and
   idempotency before restoring consequential actions.

## Regional incident

1. Declare the incident and disable payment/procurement execution flags.
2. Decide between cross-region replica promotion and point-in-time restoration
   using measured replica lag. Record the accepted data-loss boundary.
3. Deploy the pinned application revision into the recovery region.
4. Update Front Door origin only after migrations and the smoke battery pass.
5. Reconcile every queued or in-flight consequential action before workers run.
6. Fail back only through a separate approved change; do not reverse DNS during
   the same incident merely to restore the original topology.

## Required evidence

- start/end timestamps and achieved RTO/RPO;
- backup/replica identifiers and observed lag;
- Bicep deployment and image digests;
- migration, smoke, tenant-isolation and idempotency results;
- actions prevented during the incident;
- operator approval and follow-up defects.
