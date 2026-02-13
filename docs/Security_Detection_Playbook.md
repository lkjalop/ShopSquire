# Security Detection Playbook: Web, Email, Fingerprinting (JA3/JA4)

## Scope
Agent-facing detection guidance for web exploits (XSS/CSRF/SSRF/SQLi), email abuse (spoofing, phishing), and infrastructure fingerprinting (HTTP headers, TLS certificates, SSH host keys). Includes JA3/JA4 telemetry considerations and hardened security headers.

## Web Exploit Detection
- XSS: Absence or weak `Content-Security-Policy`; reflected parameters appearing in HTML/JS; missing `X-Content-Type-Options: nosniff`; inline scripts without nonces.
- CSRF: Missing anti-CSRF tokens; unsafe `SameSite=None` cookies without `Secure`; state-changing POSTs callable cross-origin.
- SSRF: External fetch endpoints accepting arbitrary URLs; lack of egress filtering; metadata IP access (169.254.169.254).
- SQLi: Error signatures; unparameterized queries; anomalous 500 spikes on inputs containing `'";--` patterns.
- RCE: Template injections; unsafe deserialization; file upload paths executing server-side.
- Header Hygiene: Ensure `Strict-Transport-Security`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`, `Cross-Origin-*` policies.

## Email Abuse Detection
- Authentication: Monitor SPF, DKIM, DMARC alignment failures; DMARC policy (`p=quarantine/reject`) for marketing domains.
- Spoofing patterns: Sending domains not aligned to envelope-from; look-alike domains; unexpected provider strings in headers.
- Bounce/Complaint webhooks: Alert on spikes; suppress campaigns; reputation recovery runbooks.
- Consent evidence: Track subscription events; enforce unsubscribe headers and links; segment transactional vs marketing.

## JA3/JA4 Telemetry
- JA3 (TLS ClientHello) and JA4 fingerprints can identify client/tooling families and anomaly patterns.
- Ingestion: Use Zeek/Suricata/Splunk add-ons to capture JA3/JA4 at the edge; correlate with web events.
- Detection: Alert on known-bad JA3 hashes; deviations from normal client JA3s; spikes in rare ciphers/extensions.
- Privacy: Treat fingerprints as pseudonymous telemetry; retain minimally and secure access.

## Fingerprinting via HTTP Headers
- Indicators: Unusual `Server`/`X-Powered-By` strings, missing security headers, custom headers indicative of specific malware/C2 frameworks.
- Action: Periodically scan site responses; compare against baselines; flag additions/removals of sensitive headers.

## Certificate Fingerprinting
- TLS cert fingerprints (SHA-256 of DER) can identify reused or self-signed infrastructure.
- Indicators: Self-signed, mismatched CN/SAN, short validity, reused fingerprints across many IPs.
- Action: Maintain known-good fingerprints for production domains; alert on changes; monitor chain validity.

## SSH Key Fingerprinting
- Capture SSH host key fingerprints (e.g., SHA256) for supplier infrastructure; detect reused keys across networks.
- Indicators: Reuse across unrelated IPs; weak algorithms; unexpected key rotations.
- Action: Maintain registry of approved host key fingerprints; alert on deviations.

## Prioritized Actions (P0→P2)
P0
- Enforce security headers (CSP, HSTS, XCTO, XFO, RP, PP, COOP/COEP/CORP).
- Capture JA3/JA4 at edge; ship to SIEM; baselines per property.
- Maintain certificate and SSH key fingerprint registries; alert on changes.
- Separate email domains; enforce SPF/DKIM/DMARC; monitor bounces/complaints.

P1
- Deploy WAF rules for XSS/SQLi; bot mitigation; rate limits.
- Add SSRF egress filters; metadata IP blocks; internal CIDR denies.
- Implement content scanning for uploads; sandbox potentially executable files.

P2
- Advanced anomaly detection for JA3/JA4; ML-based reputation; domain/IP intel feeds.
- Automated header compliance checks in CI/CD; report diffs.

## Tooling Hooks (ShopSquire)
- Header scanning: See `scripts/security/fingerprint_scan.py headers <url>`.
- TLS certificate fingerprint: `scripts/security/fingerprint_scan.py tls <host>[:port]`.
- SSH key fingerprint (optional `paramiko`): `scripts/security/fingerprint_scan.py ssh <host>[:port]`.
- Splunk HEC: Use the existing task to emit test events; correlate detections.
