# Disaster Recovery Runbook (Template)

- System: ShopSquire API
- RTO: <define>
- RPO: <define>
- Contacts: On-call SRE, Security Lead, Engineering Lead

## 1. Incident Declaration
- Trigger criteria
- Severity levels
- Communication channels

## 2. Snapshot & Containment
- Freeze changes
- Backup verification steps
- Disable non-essential workloads

## 3. Restore Procedures
- Database restore (PostgreSQL): steps + commands
- Redis restore: steps
- File/object storage restore
- Configuration secrets retrieval (Vault/Secrets Manager)

## 4. Validation
- Health checks
- Synthetic transactions
- Decision trace functionality verification

## 5. Post-Incident
- PIR (Post-Incident Review) template
- Evidence collection and retention
- Compliance notifications (regulators, customers)

## 6. Appendix
- Runbook IDs and versions
- Links to backup logs and test restores
