# Change Management Policy (Template)

## Scope
- Code changes, infrastructure, configurations, data schema

## Roles
- Requester, Reviewer, Approver, Deployer

## Workflow
1. RFC or Issue opened
2. Pull Request with linked ticket
3. Automated tests + security scans (Trivy/SAST)
4. Reviewer approval (2 approvals for high-risk)
5. Change window scheduling
6. Deploy with runbook
7. Post-deploy validation
8. Rollback plan defined

## Risk Levels
- Low, Medium, High (criteria table)

## Evidence
- PR links, CI runs, compliance registry IDs
- Decision trace IDs for changes impacting recommendations

## Key Management
- Webhook `key_id` rotation policy (quarterly)
- Secrets rotation cadence (monthly or after incident)
