# Runbook: WebhookSignatureFailureSpike

Alert: Multiple webhook signature failures detected

Steps:
- Check `shopsquire_webhook_verifications_total{status="invalid_signature"}` rate
- Inspect source IPs in security event details to identify spoofing/replay
- Validate configured secrets (Stripe/GitHub/Slack) and rotation status
- Temporarily block offending IPs; enable stricter vendor enforcement
- Notify vendor if suspected endpoint compromise; review supply-chain monitor
- Open security incident and ticket; begin forensics on recent webhook traffic
