# Security Agent Monitoring Architecture

**Generated:** 2026-01-21
**Purpose:** Agentic Security Monitoring, Supply Chain Defense, and EDR/XDR Integration

---

## Table of Contents

1. [Executive Assessment](#executive-assessment)
2. [Agent Interaction Security Model](#agent-interaction-security-model)
3. [Supply Chain Attack Detection](#supply-chain-attack-detection)
4. [API Key & Secret Verification](#api-key--secret-verification)
5. [MCP Tool Security Monitoring](#mcp-tool-security-monitoring)
6. [Human Escalation Framework](#human-escalation-framework)
7. [Prometheus/Grafana Security Pipeline](#prometheusgrafana-security-pipeline)
8. [EDR/XDR Integration (CrowdStrike, etc.)](#edrxdr-integration)
9. [TF-IDF and Anomaly Detection](#tf-idf-and-anomaly-detection)
10. [IAM Monitoring & Logging](#iam-monitoring--logging)
11. [Privacy vs Security Balance](#privacy-vs-security-balance)
12. [Vendor Comparison](#vendor-comparison)
13. [Portfolio Showcase Guide](#portfolio-showcase-guide)

---

## Executive Assessment

### Is This Overkill?

**No. You're thinking correctly.**

For an agentic system that:
- Makes autonomous decisions
- Interacts with external APIs/SaaS
- Handles payment/PII data
- Uses LLM inference

This level of security consideration is **appropriate and expected** by:
- Enterprise customers
- SOC 2 auditors
- Security-conscious investors
- Hiring managers at security-mature companies

### The Right Balance

```
┌─────────────────────────────────────────────────────────────┐
│                    SECURITY POSTURE SPECTRUM                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Too Lax          Appropriate           Overkill            │
│  ────────────────────●──────────────────────────────        │
│                      ▲                                      │
│                 YOU ARE HERE                                │
│                                                             │
│  "Detect & Escalate" model is the sweet spot:               │
│  - Comprehensive visibility                                 │
│  - Human-in-the-loop for critical decisions                │
│  - No auto-block that breaks legitimate traffic            │
│  - Audit trail for compliance                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### What Makes This Valuable (Not Paranoid)

| Concern | Why It's Valid |
|---------|----------------|
| Supply chain attacks | SolarWinds, Codecov, ua-parser-js - real incidents |
| 3rd party SaaS risks | Okta breach, LastPass breach - supply chain is weak link |
| Agent autonomy risks | LLM agents can be manipulated via prompt injection |
| API key exposure | #1 cause of cloud breaches (leaked credentials) |
| Webhook spoofing | Common attack vector for payment fraud |

---

## Agent Interaction Security Model

### What Needs Monitoring

```
┌─────────────────────────────────────────────────────────────┐
│                 AGENT INTERACTION SURFACE                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  INBOUND                        OUTBOUND                    │
│  ────────                       ────────                    │
│  • Webhook receivers            • LLM API calls             │
│  • MCP tool invocations         • Payment provider APIs     │
│  • User queries                 • Webhook dispatches        │
│  • Admin API calls              • Database queries          │
│                                 • Redis operations          │
│                                 • External SaaS (Stripe,    │
│                                   Slack, Jira, etc.)        │
│                                                             │
│  LATERAL                                                    │
│  ───────                                                    │
│  • Inter-service calls                                      │
│  • Background job execution                                 │
│  • Scheduled tasks                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Security Event Taxonomy for Agents

```python
# src/app/security/agent_monitor.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime

class AgentInteractionType(Enum):
    # Inbound
    WEBHOOK_RECEIVED = "webhook.received"
    MCP_TOOL_INVOKED = "mcp.tool.invoked"
    USER_QUERY = "user.query"
    ADMIN_ACTION = "admin.action"

    # Outbound
    LLM_API_CALL = "llm.api.call"
    PAYMENT_API_CALL = "payment.api.call"
    WEBHOOK_DISPATCHED = "webhook.dispatched"
    SAAS_API_CALL = "saas.api.call"

    # Lateral
    INTER_SERVICE_CALL = "service.internal.call"
    BACKGROUND_JOB = "job.background"

class ThreatCategory(Enum):
    SUPPLY_CHAIN = "supply_chain"
    CREDENTIAL_ABUSE = "credential_abuse"
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    WEBHOOK_SPOOFING = "webhook_spoofing"
    API_ABUSE = "api_abuse"
    ANOMALOUS_BEHAVIOR = "anomalous_behavior"

@dataclass
class AgentSecurityEvent:
    event_id: str
    timestamp: datetime
    interaction_type: AgentInteractionType
    source: str  # IP, service name, user ID
    destination: str  # API endpoint, service
    threat_category: Optional[ThreatCategory]
    severity: str  # info, low, medium, high, critical
    confidence: float  # 0.0 - 1.0
    details: Dict[str, Any]
    requires_escalation: bool
    mitre_attack_ids: list[str]
    remediation_suggested: Optional[str]
```

---

## Supply Chain Attack Detection

### Attack Vectors to Monitor

```
┌─────────────────────────────────────────────────────────────┐
│              SUPPLY CHAIN ATTACK VECTORS                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. DEPENDENCY POISONING                                    │
│     • Typosquatting (stripe → str1pe)                      │
│     • Malicious package updates                            │
│     • Compromised maintainer accounts                      │
│                                                             │
│  2. API ENDPOINT HIJACKING                                  │
│     • DNS poisoning → fake API endpoints                   │
│     • BGP hijacking → route traffic to attacker           │
│     • Compromised CDN → modified responses                 │
│                                                             │
│  3. WEBHOOK MANIPULATION                                    │
│     • Spoofed webhook payloads                             │
│     • Replay attacks                                        │
│     • Signature bypass                                      │
│                                                             │
│  4. CREDENTIAL COMPROMISE                                   │
│     • Stolen API keys from 3rd party breaches             │
│     • OAuth token theft                                     │
│     • Service account compromise                           │
│                                                             │
│  5. MCP/TOOL POISONING                                      │
│     • Malicious tool responses                             │
│     • Tool behavior drift                                   │
│     • Prompt injection via tool output                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Detection Implementation

```python
# src/app/security/supply_chain_monitor.py

import hashlib
import hmac
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import httpx
import json

@dataclass
class SupplyChainCheck:
    vendor: str
    check_type: str
    passed: bool
    details: Dict[str, Any]
    timestamp: float

class SupplyChainMonitor:
    """Monitor and verify 3rd party integrations"""

    # Known good API endpoint fingerprints
    ENDPOINT_FINGERPRINTS = {
        "stripe": {
            "api.stripe.com": {
                "expected_cert_issuer": "DigiCert",
                "expected_headers": ["stripe-version", "request-id"],
                "ip_ranges": ["99.84.0.0/16", "52.0.0.0/8"],  # AWS CloudFront
            }
        },
        "openai": {
            "api.openai.com": {
                "expected_cert_issuer": "Let's Encrypt",
                "expected_headers": ["x-request-id", "openai-organization"],
            }
        },
        "slack": {
            "hooks.slack.com": {
                "expected_cert_issuer": "Amazon",
            }
        }
    }

    # Baseline response patterns for anomaly detection
    RESPONSE_BASELINES = {}

    def __init__(self, db, redis, alerter):
        self.db = db
        self.redis = redis
        self.alerter = alerter

    async def verify_webhook_signature(
        self,
        vendor: str,
        payload: bytes,
        signature: str,
        secret: str
    ) -> Tuple[bool, str]:
        """Verify webhook signatures from known vendors"""

        if vendor == "stripe":
            # Stripe uses HMAC-SHA256
            expected = hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(f"sha256={expected}", signature):
                return False, "stripe_signature_mismatch"

        elif vendor == "github":
            # GitHub uses HMAC-SHA256
            expected = hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(f"sha256={expected}", signature):
                return False, "github_signature_mismatch"

        elif vendor == "slack":
            # Slack uses timestamp + signature
            # signature = 'v0=' + HMAC-SHA256(secret, 'v0:' + timestamp + ':' + body)
            parts = signature.split("=")
            if len(parts) != 2:
                return False, "slack_signature_format_invalid"

        return True, "signature_valid"

    async def check_endpoint_integrity(
        self,
        vendor: str,
        endpoint: str
    ) -> SupplyChainCheck:
        """Verify API endpoint hasn't been compromised"""

        fingerprint = self.ENDPOINT_FINGERPRINTS.get(vendor, {}).get(endpoint)
        if not fingerprint:
            return SupplyChainCheck(
                vendor=vendor,
                check_type="endpoint_integrity",
                passed=True,  # No baseline = can't check
                details={"reason": "no_baseline_configured"},
                timestamp=time.time()
            )

        issues = []

        # Check TLS certificate
        try:
            async with httpx.AsyncClient() as client:
                response = await client.head(f"https://{endpoint}", timeout=5.0)

                # Verify expected headers present
                for expected_header in fingerprint.get("expected_headers", []):
                    if expected_header.lower() not in [h.lower() for h in response.headers]:
                        issues.append(f"missing_header:{expected_header}")

        except Exception as e:
            issues.append(f"connection_error:{str(e)}")

        passed = len(issues) == 0

        if not passed:
            await self.alerter.escalate(
                severity="high",
                category="supply_chain",
                message=f"Endpoint integrity check failed for {vendor}/{endpoint}",
                details={"issues": issues}
            )

        return SupplyChainCheck(
            vendor=vendor,
            check_type="endpoint_integrity",
            passed=passed,
            details={"issues": issues},
            timestamp=time.time()
        )

    async def detect_response_anomaly(
        self,
        vendor: str,
        endpoint: str,
        response_body: Dict[str, Any]
    ) -> Tuple[bool, float, str]:
        """Detect anomalous API responses using statistical analysis"""

        baseline_key = f"baseline:{vendor}:{endpoint}"
        baseline = self.redis.get(baseline_key)

        if not baseline:
            # First time seeing this endpoint, establish baseline
            self._update_baseline(vendor, endpoint, response_body)
            return False, 0.0, "baseline_established"

        baseline = json.loads(baseline)

        # Check for structural anomalies
        anomalies = []

        # 1. New unexpected fields
        current_fields = set(self._extract_field_paths(response_body))
        baseline_fields = set(baseline.get("fields", []))
        new_fields = current_fields - baseline_fields

        if new_fields:
            anomalies.append(f"new_fields:{list(new_fields)[:5]}")

        # 2. Missing expected fields
        missing_fields = baseline_fields - current_fields
        if missing_fields:
            anomalies.append(f"missing_fields:{list(missing_fields)[:5]}")

        # 3. Type changes
        for field, expected_type in baseline.get("field_types", {}).items():
            current_value = self._get_nested_value(response_body, field)
            if current_value is not None:
                current_type = type(current_value).__name__
                if current_type != expected_type:
                    anomalies.append(f"type_change:{field}:{expected_type}->{current_type}")

        # 4. Suspicious content patterns
        response_str = json.dumps(response_body)
        suspicious_patterns = [
            ("base64_executable", r"TVqQAAMAAAAEAAAA"),  # PE header
            ("script_tag", r"<script"),
            ("eval_injection", r"eval\s*\("),
            ("data_uri", r"data:text/html"),
        ]

        import re
        for pattern_name, pattern in suspicious_patterns:
            if re.search(pattern, response_str, re.IGNORECASE):
                anomalies.append(f"suspicious_content:{pattern_name}")

        is_anomaly = len(anomalies) > 0
        confidence = min(1.0, len(anomalies) * 0.3)

        if is_anomaly and confidence > 0.5:
            await self.alerter.escalate(
                severity="high" if confidence > 0.7 else "medium",
                category="supply_chain",
                message=f"Anomalous response from {vendor}/{endpoint}",
                details={"anomalies": anomalies, "confidence": confidence}
            )

        return is_anomaly, confidence, "|".join(anomalies)

    def _extract_field_paths(self, obj: Any, prefix: str = "") -> list[str]:
        """Extract all field paths from nested object"""
        paths = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else key
                paths.append(path)
                paths.extend(self._extract_field_paths(value, path))
        elif isinstance(obj, list) and obj:
            paths.extend(self._extract_field_paths(obj[0], f"{prefix}[]"))
        return paths

    def _get_nested_value(self, obj: Dict, path: str) -> Any:
        """Get value at nested path"""
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def _update_baseline(self, vendor: str, endpoint: str, response: Dict):
        """Update response baseline for anomaly detection"""
        baseline = {
            "fields": self._extract_field_paths(response),
            "field_types": {},
            "updated_at": time.time(),
            "sample_count": 1
        }

        # Record field types
        for field in baseline["fields"]:
            value = self._get_nested_value(response, field)
            if value is not None:
                baseline["field_types"][field] = type(value).__name__

        self.redis.setex(
            f"baseline:{vendor}:{endpoint}",
            86400 * 7,  # 7 day TTL
            json.dumps(baseline)
        )
```

### Webhook Security Middleware

```python
# src/app/middleware/webhook_security.py

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import time
import hashlib

class WebhookSecurityMiddleware(BaseHTTPMiddleware):
    """Validate and monitor all incoming webhooks"""

    WEBHOOK_PATHS = [
        "/api/v1/orchestrator/events/",
        "/api/v1/admin/connectors/test",
    ]

    def __init__(self, app, supply_chain_monitor, security_logger):
        super().__init__(app)
        self.monitor = supply_chain_monitor
        self.logger = security_logger

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Check if this is a webhook endpoint
        is_webhook = any(path.startswith(p) for p in self.WEBHOOK_PATHS)

        if is_webhook:
            # Extract vendor from path or headers
            vendor = self._detect_vendor(request)

            # Read body for signature verification
            body = await request.body()

            # Log the webhook receipt
            await self.logger.log_event({
                "type": "webhook.received",
                "vendor": vendor,
                "path": path,
                "body_hash": hashlib.sha256(body).hexdigest()[:16],
                "timestamp": time.time(),
                "source_ip": request.client.host
            })

            # Verify signature if vendor provides one
            signature = (
                request.headers.get("stripe-signature") or
                request.headers.get("x-hub-signature-256") or
                request.headers.get("x-slack-signature")
            )

            if signature and vendor:
                secret = self._get_webhook_secret(vendor)
                if secret:
                    valid, reason = await self.monitor.verify_webhook_signature(
                        vendor, body, signature, secret
                    )
                    if not valid:
                        await self.logger.log_event({
                            "type": "webhook.signature_failed",
                            "vendor": vendor,
                            "reason": reason,
                            "severity": "high"
                        })
                        raise HTTPException(401, "Invalid webhook signature")

            # Check for replay attacks
            event_id = request.headers.get("x-event-id") or \
                       request.headers.get("stripe-event-id")
            if event_id:
                if await self._is_replay(event_id):
                    await self.logger.log_event({
                        "type": "webhook.replay_detected",
                        "event_id": event_id,
                        "severity": "high"
                    })
                    raise HTTPException(409, "Duplicate event")
                await self._mark_seen(event_id)

        response = await call_next(request)
        return response

    def _detect_vendor(self, request: Request) -> str:
        """Detect webhook vendor from request"""
        if "stripe-signature" in request.headers:
            return "stripe"
        if "x-github-event" in request.headers:
            return "github"
        if "x-slack-signature" in request.headers:
            return "slack"
        if "x-shopify-hmac-sha256" in request.headers:
            return "shopify"
        return "unknown"

    async def _is_replay(self, event_id: str) -> bool:
        """Check if event was already processed"""
        key = f"webhook:seen:{event_id}"
        return self.monitor.redis.exists(key)

    async def _mark_seen(self, event_id: str):
        """Mark event as processed"""
        key = f"webhook:seen:{event_id}"
        self.monitor.redis.setex(key, 86400, "1")  # 24hr dedup window
```

---

## API Key & Secret Verification

### Key Security Monitoring

```python
# src/app/security/key_monitor.py

import re
import time
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
import hashlib

@dataclass
class KeySecurityEvent:
    key_hash: str  # Never log actual key
    event_type: str
    severity: str
    details: Dict[str, Any]
    timestamp: float

class APIKeyMonitor:
    """Monitor API key usage and detect compromise"""

    # Patterns that indicate leaked keys
    EXPOSURE_INDICATORS = [
        # GitHub secret scanning patterns
        r"sk_live_[a-zA-Z0-9]{24}",  # Stripe live key
        r"sk_test_[a-zA-Z0-9]{24}",  # Stripe test key
        r"ghp_[a-zA-Z0-9]{36}",      # GitHub PAT
        r"xoxb-[0-9]{11}-[0-9]{11}-[a-zA-Z0-9]{24}",  # Slack bot token
    ]

    def __init__(self, db, redis, alerter):
        self.db = db
        self.redis = redis
        self.alerter = alerter

    async def verify_key_not_compromised(
        self,
        key: str,
        vendor: str
    ) -> Tuple[bool, str]:
        """Check if key appears in known breach databases"""

        key_hash = hashlib.sha256(key.encode()).hexdigest()

        # Check internal blocklist
        if self.redis.sismember("compromised_keys", key_hash):
            return False, "key_in_blocklist"

        # Check usage anomalies
        anomaly = await self._check_usage_anomaly(key_hash)
        if anomaly:
            return False, f"usage_anomaly:{anomaly}"

        return True, "key_verified"

    async def _check_usage_anomaly(self, key_hash: str) -> Optional[str]:
        """Detect anomalous key usage patterns"""

        usage_key = f"key_usage:{key_hash}"
        usage = self.redis.hgetall(usage_key)

        if not usage:
            return None

        # Check for impossible travel
        last_ip = usage.get("last_ip")
        last_country = usage.get("last_country")
        last_time = float(usage.get("last_time", 0))

        # If same key used from different countries within 1 hour
        # that's physically impossible (unless VPN, but flag anyway)
        current_time = time.time()
        if last_country and (current_time - last_time) < 3600:
            # Would need to check current request country here
            pass

        # Check for burst usage (potential credential stuffing)
        request_count = int(usage.get("requests_1min", 0))
        if request_count > 100:
            return "burst_usage"

        return None

    async def log_key_usage(
        self,
        key_hash: str,
        endpoint: str,
        source_ip: str,
        success: bool
    ):
        """Log API key usage for anomaly detection"""

        usage_key = f"key_usage:{key_hash}"

        pipe = self.redis.pipeline()
        pipe.hincrby(usage_key, "total_requests", 1)
        pipe.hset(usage_key, "last_ip", source_ip)
        pipe.hset(usage_key, "last_time", str(time.time()))
        pipe.hset(usage_key, "last_endpoint", endpoint)

        if not success:
            pipe.hincrby(usage_key, "failed_requests", 1)

        # Track requests per minute for burst detection
        minute_key = f"key_rpm:{key_hash}:{int(time.time() / 60)}"
        pipe.incr(minute_key)
        pipe.expire(minute_key, 120)

        pipe.expire(usage_key, 86400)
        pipe.execute()

        # Check for failed request threshold
        usage = self.redis.hgetall(usage_key)
        failed = int(usage.get("failed_requests", 0))
        total = int(usage.get("total_requests", 1))

        if total > 10 and (failed / total) > 0.5:
            await self.alerter.escalate(
                severity="high",
                category="credential_abuse",
                message=f"High failure rate for API key",
                details={
                    "key_hash": key_hash[:16],
                    "failed_rate": failed / total,
                    "last_endpoint": endpoint
                }
            )

    def scan_for_exposed_keys(self, text: str) -> List[Dict[str, Any]]:
        """Scan text for accidentally exposed API keys"""

        findings = []

        for pattern in self.EXPOSURE_INDICATORS:
            matches = re.findall(pattern, text)
            for match in matches:
                findings.append({
                    "pattern": pattern,
                    "key_prefix": match[:8] + "...",
                    "key_hash": hashlib.sha256(match.encode()).hexdigest()[:16]
                })

        return findings
```

---

## MCP Tool Security Monitoring

### Tool Invocation Security

```python
# src/app/security/mcp_monitor.py

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import time
import json
import hashlib

@dataclass
class MCPToolInvocation:
    tool_name: str
    input_hash: str
    output_hash: str
    duration_ms: float
    timestamp: float

class MCPSecurityMonitor:
    """Monitor MCP tool invocations for security issues"""

    # Tools that require extra scrutiny
    HIGH_RISK_TOOLS = [
        "execute_code",
        "file_write",
        "http_request",
        "database_query",
        "send_email",
        "api_call"
    ]

    # Output patterns that indicate compromise
    SUSPICIOUS_OUTPUT_PATTERNS = [
        r"password\s*[=:]\s*['\"]",
        r"api[_-]?key\s*[=:]\s*['\"]",
        r"BEGIN\s+(RSA|DSA|EC)\s+PRIVATE\s+KEY",
        r"AKIA[0-9A-Z]{16}",  # AWS access key
        r"-----BEGIN\s+CERTIFICATE-----",
    ]

    def __init__(self, db, redis, alerter):
        self.db = db
        self.redis = redis
        self.alerter = alerter

    async def pre_invoke_check(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        agent_context: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Security check before tool invocation"""

        # Check if tool is allowed for this agent context
        allowed_tools = agent_context.get("allowed_tools", [])
        if allowed_tools and tool_name not in allowed_tools:
            await self.alerter.escalate(
                severity="high",
                category="privilege_escalation",
                message=f"Agent attempted to use unauthorized tool: {tool_name}",
                details={"agent": agent_context.get("agent_name"), "tool": tool_name}
            )
            return False, "tool_not_allowed"

        # Extra validation for high-risk tools
        if tool_name in self.HIGH_RISK_TOOLS:
            # Check for prompt injection in tool input
            input_str = json.dumps(tool_input)

            injection_patterns = [
                r"ignore\s+(previous|above)\s+instructions",
                r"disregard\s+.*\s+instructions",
                r"you\s+are\s+now\s+",
                r"new\s+instructions:",
            ]

            import re
            for pattern in injection_patterns:
                if re.search(pattern, input_str, re.IGNORECASE):
                    await self.alerter.escalate(
                        severity="critical",
                        category="prompt_injection",
                        message=f"Prompt injection detected in tool input",
                        details={"tool": tool_name, "pattern": pattern}
                    )
                    return False, "prompt_injection_detected"

        return True, "approved"

    async def post_invoke_check(
        self,
        tool_name: str,
        tool_output: Any,
        duration_ms: float
    ) -> Tuple[bool, List[str]]:
        """Security check after tool invocation"""

        issues = []
        output_str = json.dumps(tool_output) if not isinstance(tool_output, str) else tool_output

        # Check for sensitive data in output
        import re
        for pattern in self.SUSPICIOUS_OUTPUT_PATTERNS:
            if re.search(pattern, output_str, re.IGNORECASE):
                issues.append(f"sensitive_data_in_output:{pattern[:20]}")

        # Check for data exfiltration attempts
        # (unusually large output from read-only tools)
        if tool_name in ["database_query", "file_read"] and len(output_str) > 100000:
            issues.append("large_data_extraction")

        # Check for timing anomalies
        baseline = await self._get_timing_baseline(tool_name)
        if baseline and duration_ms > baseline * 10:
            issues.append(f"timing_anomaly:expected={baseline}ms,actual={duration_ms}ms")

        if issues:
            severity = "critical" if "sensitive_data" in str(issues) else "high"
            await self.alerter.escalate(
                severity=severity,
                category="data_exfiltration" if "extraction" in str(issues) else "anomalous_behavior",
                message=f"Security issues detected in tool output",
                details={"tool": tool_name, "issues": issues}
            )

        # Update baseline
        await self._update_timing_baseline(tool_name, duration_ms)

        return len(issues) == 0, issues

    async def _get_timing_baseline(self, tool_name: str) -> Optional[float]:
        """Get expected timing for tool"""
        baseline = self.redis.get(f"tool_timing:{tool_name}")
        return float(baseline) if baseline else None

    async def _update_timing_baseline(self, tool_name: str, duration_ms: float):
        """Update timing baseline with EWMA"""
        key = f"tool_timing:{tool_name}"
        current = self.redis.get(key)

        if current:
            # EWMA with alpha=0.1
            new_baseline = 0.9 * float(current) + 0.1 * duration_ms
        else:
            new_baseline = duration_ms

        self.redis.setex(key, 86400 * 7, str(new_baseline))

    async def log_invocation(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        duration_ms: float,
        agent_context: Dict[str, Any]
    ):
        """Log tool invocation for audit trail"""

        invocation = {
            "id": hashlib.sha256(f"{time.time()}{tool_name}".encode()).hexdigest()[:16],
            "tool_name": tool_name,
            "input_hash": hashlib.sha256(json.dumps(tool_input).encode()).hexdigest()[:16],
            "output_hash": hashlib.sha256(str(tool_output).encode()).hexdigest()[:16],
            "duration_ms": duration_ms,
            "agent_name": agent_context.get("agent_name"),
            "session_id": agent_context.get("session_id"),
            "timestamp": time.time()
        }

        # Store in DB for audit
        self.db.execute("""
            INSERT INTO mcp_invocations
            (id, tool_name, input_hash, output_hash, duration_ms, agent_name, session_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(invocation.values()))
        self.db.commit()

        # Also push to Redis for real-time monitoring
        self.redis.lpush("mcp_invocations:recent", json.dumps(invocation))
        self.redis.ltrim("mcp_invocations:recent", 0, 999)
```

---

## Human Escalation Framework

### Escalation Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 ESCALATION DECISION TREE                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Security Event Detected                                    │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │ Severity Check  │                                        │
│  └────────┬────────┘                                        │
│           │                                                 │
│     ┌─────┴─────┐                                           │
│     │           │                                           │
│  Critical    High/Medium                                    │
│     │           │                                           │
│     ▼           ▼                                           │
│  ┌──────┐  ┌────────────┐                                   │
│  │BLOCK │  │ Confidence │                                   │
│  │ +    │  │   Check    │                                   │
│  │PAGE  │  └─────┬──────┘                                   │
│  └──────┘        │                                          │
│           ┌──────┴──────┐                                   │
│           │             │                                   │
│        >0.8          <0.8                                   │
│           │             │                                   │
│           ▼             ▼                                   │
│     ┌──────────┐  ┌───────────┐                             │
│     │ AUTO     │  │ QUEUE FOR │                             │
│     │ ESCALATE │  │ HUMAN     │                             │
│     │ + ALERT  │  │ REVIEW    │                             │
│     └──────────┘  └───────────┘                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Implementation

```python
# src/app/security/escalation.py

from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import time
import json
import asyncio

class EscalationLevel(Enum):
    LOG_ONLY = "log_only"           # Just log, no human
    QUEUE_REVIEW = "queue_review"   # Add to human review queue
    ALERT_TEAM = "alert_team"       # Send Slack/email alert
    PAGE_ONCALL = "page_oncall"     # PagerDuty/Opsgenie
    BLOCK_AND_PAGE = "block_and_page"  # Block request + page

@dataclass
class EscalationPolicy:
    severity: str
    confidence_threshold: float
    escalation_level: EscalationLevel
    auto_block: bool
    notify_channels: List[str]

class HumanEscalationFramework:
    """Framework for escalating security events to human observers"""

    POLICIES = {
        "critical": EscalationPolicy(
            severity="critical",
            confidence_threshold=0.5,
            escalation_level=EscalationLevel.BLOCK_AND_PAGE,
            auto_block=True,
            notify_channels=["pagerduty", "slack-security", "email-security"]
        ),
        "high": EscalationPolicy(
            severity="high",
            confidence_threshold=0.7,
            escalation_level=EscalationLevel.ALERT_TEAM,
            auto_block=False,
            notify_channels=["slack-security", "email-security"]
        ),
        "medium": EscalationPolicy(
            severity="medium",
            confidence_threshold=0.8,
            escalation_level=EscalationLevel.QUEUE_REVIEW,
            auto_block=False,
            notify_channels=["slack-alerts"]
        ),
        "low": EscalationPolicy(
            severity="low",
            confidence_threshold=0.9,
            escalation_level=EscalationLevel.LOG_ONLY,
            auto_block=False,
            notify_channels=[]
        )
    }

    def __init__(self, db, redis, notification_service):
        self.db = db
        self.redis = redis
        self.notifier = notification_service

    async def escalate(
        self,
        severity: str,
        category: str,
        message: str,
        details: Dict[str, Any],
        confidence: float = 1.0
    ) -> Dict[str, Any]:
        """Escalate security event based on policy"""

        policy = self.POLICIES.get(severity, self.POLICIES["low"])

        # Check if confidence meets threshold
        if confidence < policy.confidence_threshold:
            # Not confident enough, queue for human review instead
            return await self._queue_for_review(severity, category, message, details, confidence)

        # Create escalation record
        escalation_id = await self._create_escalation_record(
            severity, category, message, details, confidence, policy
        )

        # Execute escalation based on level
        result = {
            "escalation_id": escalation_id,
            "level": policy.escalation_level.value,
            "blocked": False,
            "notifications_sent": []
        }

        if policy.auto_block:
            result["blocked"] = True

        # Send notifications
        for channel in policy.notify_channels:
            try:
                await self._notify(channel, escalation_id, severity, category, message, details)
                result["notifications_sent"].append(channel)
            except Exception as e:
                result["notification_errors"] = result.get("notification_errors", [])
                result["notification_errors"].append(f"{channel}:{str(e)}")

        return result

    async def _queue_for_review(
        self,
        severity: str,
        category: str,
        message: str,
        details: Dict[str, Any],
        confidence: float
    ) -> Dict[str, Any]:
        """Queue event for human review (not confident enough to auto-escalate)"""

        review_id = f"review_{int(time.time() * 1000)}"

        review_item = {
            "id": review_id,
            "severity": severity,
            "category": category,
            "message": message,
            "details": details,
            "confidence": confidence,
            "status": "pending",
            "created_at": time.time()
        }

        # Add to review queue
        self.redis.lpush("security:review_queue", json.dumps(review_item))

        # Store for retrieval
        self.redis.setex(f"security:review:{review_id}", 86400 * 7, json.dumps(review_item))

        return {
            "escalation_id": review_id,
            "level": "queue_review",
            "blocked": False,
            "requires_human_decision": True
        }

    async def _create_escalation_record(
        self,
        severity: str,
        category: str,
        message: str,
        details: Dict[str, Any],
        confidence: float,
        policy: EscalationPolicy
    ) -> str:
        """Create database record for escalation"""

        escalation_id = f"esc_{int(time.time() * 1000)}"

        self.db.execute("""
            INSERT INTO security_escalations
            (id, severity, category, message, details, confidence, escalation_level, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            escalation_id,
            severity,
            category,
            message,
            json.dumps(details),
            confidence,
            policy.escalation_level.value,
            time.time()
        ))
        self.db.commit()

        return escalation_id

    async def _notify(
        self,
        channel: str,
        escalation_id: str,
        severity: str,
        category: str,
        message: str,
        details: Dict[str, Any]
    ):
        """Send notification to channel"""

        if channel.startswith("slack"):
            await self.notifier.send_slack(
                channel=channel.replace("slack-", "#"),
                message=self._format_slack_message(escalation_id, severity, category, message, details)
            )

        elif channel == "pagerduty":
            await self.notifier.page_oncall(
                severity=severity,
                summary=f"[{severity.upper()}] {category}: {message}",
                details=details
            )

        elif channel.startswith("email"):
            await self.notifier.send_email(
                to=self._get_email_recipients(channel),
                subject=f"[ShopSquire Security] {severity.upper()}: {category}",
                body=self._format_email_body(escalation_id, severity, category, message, details)
            )

    def _format_slack_message(
        self,
        escalation_id: str,
        severity: str,
        category: str,
        message: str,
        details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format Slack Block Kit message"""

        severity_emoji = {
            "critical": ":rotating_light:",
            "high": ":warning:",
            "medium": ":large_yellow_circle:",
            "low": ":information_source:"
        }

        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{severity_emoji.get(severity, ':question:')} Security Alert: {category}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Severity:* {severity}"},
                        {"type": "mrkdwn", "text": f"*ID:* {escalation_id}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Message:* {message}"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{json.dumps(details, indent=2)[:500]}```"}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View in Dashboard"},
                            "url": f"https://shopsquire.app/admin/security/{escalation_id}"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Acknowledge"},
                            "action_id": f"ack_{escalation_id}"
                        }
                    ]
                }
            ]
        }

    async def get_review_queue(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get pending items in review queue"""
        items = self.redis.lrange("security:review_queue", 0, limit - 1)
        return [json.loads(item) for item in items]

    async def resolve_review(
        self,
        review_id: str,
        resolution: str,
        resolved_by: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Human resolves a queued review item"""

        review_data = self.redis.get(f"security:review:{review_id}")
        if not review_data:
            return {"error": "review_not_found"}

        review = json.loads(review_data)
        review["status"] = resolution  # "confirmed_threat", "false_positive", "needs_investigation"
        review["resolved_by"] = resolved_by
        review["resolved_at"] = time.time()
        review["resolution_notes"] = notes

        # Update storage
        self.redis.setex(f"security:review:{review_id}", 86400 * 30, json.dumps(review))

        # Remove from queue
        self.redis.lrem("security:review_queue", 1, review_data)

        # If confirmed threat, trigger follow-up actions
        if resolution == "confirmed_threat":
            await self.escalate(
                severity=review["severity"],
                category=review["category"],
                message=f"[HUMAN CONFIRMED] {review['message']}",
                details={**review["details"], "confirmed_by": resolved_by},
                confidence=1.0  # Human confirmed = 100% confidence
            )

        return review
```

---

## Prometheus/Grafana Security Pipeline

### Security Metrics

```python
# src/app/observability/security_metrics.py

from prometheus_client import Counter, Histogram, Gauge, Info

# === THREAT DETECTION METRICS ===

security_events_total = Counter(
    'shopsquire_security_events_total',
    'Total security events detected',
    ['severity', 'category', 'source']
)

threat_detection_latency = Histogram(
    'shopsquire_threat_detection_seconds',
    'Time to analyze request for threats',
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

active_threats = Gauge(
    'shopsquire_active_threats',
    'Number of unresolved security events',
    ['severity']
)

# === SUPPLY CHAIN METRICS ===

supply_chain_checks_total = Counter(
    'shopsquire_supply_chain_checks_total',
    'Total supply chain verification checks',
    ['vendor', 'check_type', 'result']
)

webhook_signature_failures = Counter(
    'shopsquire_webhook_signature_failures_total',
    'Webhook signature verification failures',
    ['vendor', 'reason']
)

api_response_anomalies = Counter(
    'shopsquire_api_response_anomalies_total',
    'Anomalous responses from external APIs',
    ['vendor', 'anomaly_type']
)

# === ESCALATION METRICS ===

escalations_total = Counter(
    'shopsquire_escalations_total',
    'Total security escalations',
    ['severity', 'level', 'category']
)

escalation_response_time = Histogram(
    'shopsquire_escalation_response_seconds',
    'Time from escalation to human response',
    buckets=[60, 300, 900, 1800, 3600, 7200, 14400]  # 1min to 4hrs
)

review_queue_depth = Gauge(
    'shopsquire_security_review_queue_depth',
    'Number of items pending human review'
)

# === API KEY METRICS ===

api_key_usage_total = Counter(
    'shopsquire_api_key_usage_total',
    'API key usage events',
    ['key_hash_prefix', 'endpoint', 'result']
)

api_key_anomalies = Counter(
    'shopsquire_api_key_anomalies_total',
    'Anomalous API key usage detected',
    ['anomaly_type']
)

# === MCP TOOL METRICS ===

mcp_invocations_total = Counter(
    'shopsquire_mcp_invocations_total',
    'MCP tool invocations',
    ['tool_name', 'agent_name', 'result']
)

mcp_security_blocks = Counter(
    'shopsquire_mcp_security_blocks_total',
    'MCP tool invocations blocked for security',
    ['tool_name', 'reason']
)

# === AGENT BEHAVIOR METRICS ===

agent_decisions_total = Counter(
    'shopsquire_agent_decisions_total',
    'Agent decisions made',
    ['agent_name', 'decision_type', 'outcome']
)

agent_approval_rate = Gauge(
    'shopsquire_agent_approval_rate',
    'Human approval rate for agent decisions',
    ['agent_name']
)

agent_autonomy_level = Gauge(
    'shopsquire_agent_autonomy_level',
    'Current autonomy level (0-100)',
    ['agent_name']
)
```

### Grafana Security Dashboard

```json
{
  "dashboard": {
    "title": "ShopSquire Security Operations Center",
    "tags": ["security", "soc"],
    "timezone": "browser",
    "refresh": "10s",
    "panels": [
      {
        "title": "Threat Overview",
        "type": "stat",
        "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
        "targets": [
          {
            "expr": "sum(shopsquire_active_threats)",
            "legendFormat": "Active Threats"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "thresholds": {
              "steps": [
                {"color": "green", "value": 0},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 5}
              ]
            }
          }
        }
      },
      {
        "title": "Security Events by Severity (24h)",
        "type": "piechart",
        "gridPos": {"h": 8, "w": 6, "x": 6, "y": 0},
        "targets": [
          {
            "expr": "sum by (severity) (increase(shopsquire_security_events_total[24h]))",
            "legendFormat": "{{severity}}"
          }
        ]
      },
      {
        "title": "Threat Detection Timeline",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "targets": [
          {
            "expr": "sum by (category) (rate(shopsquire_security_events_total[5m]))",
            "legendFormat": "{{category}}"
          }
        ]
      },
      {
        "title": "Supply Chain Health",
        "type": "table",
        "gridPos": {"h": 6, "w": 12, "x": 0, "y": 8},
        "targets": [
          {
            "expr": "sum by (vendor, result) (increase(shopsquire_supply_chain_checks_total[1h]))",
            "format": "table"
          }
        ]
      },
      {
        "title": "Webhook Signature Failures",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 12, "x": 12, "y": 8},
        "targets": [
          {
            "expr": "sum by (vendor) (rate(shopsquire_webhook_signature_failures_total[5m]))",
            "legendFormat": "{{vendor}}"
          }
        ],
        "alert": {
          "conditions": [
            {
              "evaluator": {"params": [0], "type": "gt"},
              "reducer": {"type": "sum"},
              "query": {"params": ["A", "5m", "now"]}
            }
          ],
          "name": "Webhook Signature Failure Alert",
          "message": "Webhook signature failures detected - possible spoofing attempt"
        }
      },
      {
        "title": "Human Review Queue",
        "type": "gauge",
        "gridPos": {"h": 4, "w": 6, "x": 0, "y": 14},
        "targets": [
          {
            "expr": "shopsquire_security_review_queue_depth"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "max": 50,
            "thresholds": {
              "steps": [
                {"color": "green", "value": 0},
                {"color": "yellow", "value": 10},
                {"color": "red", "value": 25}
              ]
            }
          }
        }
      },
      {
        "title": "Escalation Response Time (p95)",
        "type": "stat",
        "gridPos": {"h": 4, "w": 6, "x": 6, "y": 14},
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(shopsquire_escalation_response_seconds_bucket[1h]))",
            "legendFormat": "p95 Response Time"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "unit": "s"
          }
        }
      },
      {
        "title": "Agent Approval Rate",
        "type": "bargauge",
        "gridPos": {"h": 4, "w": 12, "x": 12, "y": 14},
        "targets": [
          {
            "expr": "shopsquire_agent_approval_rate",
            "legendFormat": "{{agent_name}}"
          }
        ],
        "fieldConfig": {
          "defaults": {
            "max": 1,
            "unit": "percentunit"
          }
        }
      },
      {
        "title": "MCP Tool Security Blocks",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 12, "x": 0, "y": 18},
        "targets": [
          {
            "expr": "sum by (tool_name, reason) (rate(shopsquire_mcp_security_blocks_total[5m]))",
            "legendFormat": "{{tool_name}}: {{reason}}"
          }
        ]
      },
      {
        "title": "API Key Anomalies",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 12, "x": 12, "y": 18},
        "targets": [
          {
            "expr": "sum by (anomaly_type) (rate(shopsquire_api_key_anomalies_total[5m]))",
            "legendFormat": "{{anomaly_type}}"
          }
        ]
      }
    ]
  }
}
```

### Alert Rules

```yaml
# config/observability/prometheus/security_alerts.yml

groups:
  - name: security_alerts
    rules:
      # Critical: Supply chain compromise indicators
      - alert: SupplyChainAnomalyDetected
        expr: sum(rate(shopsquire_api_response_anomalies_total[5m])) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Supply chain anomaly detected"
          description: "Anomalous response from external API - possible compromise"

      # Critical: Webhook spoofing attempt
      - alert: WebhookSignatureFailureSpike
        expr: sum(rate(shopsquire_webhook_signature_failures_total[5m])) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Multiple webhook signature failures"
          description: "{{ $value }} webhook signature failures in 5 minutes"

      # High: Review queue backup
      - alert: SecurityReviewQueueBacklog
        expr: shopsquire_security_review_queue_depth > 25
        for: 15m
        labels:
          severity: high
        annotations:
          summary: "Security review queue backlog"
          description: "{{ $value }} items pending human review"

      # High: Agent approval rate drop
      - alert: AgentApprovalRateDrop
        expr: shopsquire_agent_approval_rate < 0.7
        for: 30m
        labels:
          severity: high
        annotations:
          summary: "Agent approval rate dropped"
          description: "Agent {{ $labels.agent_name }} approval rate is {{ $value }}"

      # High: MCP tool abuse
      - alert: MCPToolSecurityBlocks
        expr: sum(rate(shopsquire_mcp_security_blocks_total[5m])) > 10
        for: 5m
        labels:
          severity: high
        annotations:
          summary: "High rate of MCP tool security blocks"
          description: "{{ $value }} tool invocations blocked per second"

      # Medium: Unusual API key usage
      - alert: APIKeyAnomalousUsage
        expr: sum(rate(shopsquire_api_key_anomalies_total[15m])) > 0
        for: 5m
        labels:
          severity: medium
        annotations:
          summary: "Anomalous API key usage detected"
          description: "Unusual usage pattern for API key"
```

---

## EDR/XDR Integration

### Architecture for Security Telemetry Streaming

```
┌─────────────────────────────────────────────────────────────┐
│                 SECURITY TELEMETRY PIPELINE                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ShopSquire App                                             │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────┐                                            │
│  │ Security    │                                            │
│  │ Observer    │                                            │
│  └──────┬──────┘                                            │
│         │                                                   │
│    ┌────┴────┬────────────┬───────────┐                    │
│    │         │            │           │                    │
│    ▼         ▼            ▼           ▼                    │
│ Prometheus  Kafka/       SIEM        EDR/XDR              │
│ (metrics)   Redis        (logs)      (endpoint)           │
│             (stream)                                       │
│    │         │            │           │                    │
│    ▼         ▼            ▼           ▼                    │
│ Grafana   Custom       Splunk/     CrowdStrike/          │
│           Consumers    Elastic     SentinelOne            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### CrowdStrike Integration

```python
# src/app/integrations/crowdstrike.py

import httpx
from typing import Dict, Any
import time
import os

class CrowdStrikeIntegration:
    """Send security telemetry to CrowdStrike Falcon"""

    def __init__(self):
        self.client_id = os.getenv("CROWDSTRIKE_CLIENT_ID")
        self.client_secret = os.getenv("CROWDSTRIKE_CLIENT_SECRET")
        self.base_url = os.getenv("CROWDSTRIKE_API_URL", "https://api.crowdstrike.com")
        self._token = None
        self._token_expires = 0

    async def _get_token(self) -> str:
        """Get OAuth2 token"""
        if self._token and time.time() < self._token_expires:
            return self._token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/oauth2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                }
            )
            data = response.json()
            self._token = data["access_token"]
            self._token_expires = time.time() + data["expires_in"] - 60
            return self._token

    async def submit_ioc(
        self,
        indicator_type: str,  # "ipv4", "domain", "sha256", etc.
        value: str,
        description: str,
        severity: str,
        source: str = "shopsquire"
    ):
        """Submit Indicator of Compromise to CrowdStrike"""

        token = await self._get_token()

        payload = {
            "indicators": [
                {
                    "type": indicator_type,
                    "value": value,
                    "description": description,
                    "severity": severity,
                    "source": source,
                    "applied_globally": True,
                    "action": "detect"  # or "block"
                }
            ]
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/iocs/entities/indicators/v1",
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )
            return response.json()

    async def report_detection(
        self,
        event_type: str,
        details: Dict[str, Any],
        severity: str
    ):
        """Report custom detection to CrowdStrike"""

        token = await self._get_token()

        # Map to CrowdStrike detection format
        detection = {
            "detection_id": f"shopsquire_{int(time.time() * 1000)}",
            "timestamp": time.time(),
            "event_type": event_type,
            "severity": self._map_severity(severity),
            "description": details.get("message", "ShopSquire security event"),
            "metadata": details
        }

        # Use CrowdStrike's custom IOC or detection API
        # Actual implementation depends on your CrowdStrike tier

        return detection

    def _map_severity(self, severity: str) -> int:
        """Map internal severity to CrowdStrike scale (1-5)"""
        mapping = {
            "critical": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "info": 1
        }
        return mapping.get(severity, 2)
```

### Generic SIEM/XDR Connector

```python
# src/app/integrations/security_telemetry.py

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import json
import time
import asyncio

class SecurityTelemetryConnector(ABC):
    """Abstract base for security telemetry destinations"""

    @abstractmethod
    async def send_event(self, event: Dict[str, Any]) -> bool:
        pass

    @abstractmethod
    async def send_batch(self, events: List[Dict[str, Any]]) -> int:
        pass


class SplunkHECConnector(SecurityTelemetryConnector):
    """Send events to Splunk via HTTP Event Collector"""

    def __init__(self, hec_url: str, hec_token: str):
        self.hec_url = hec_url
        self.hec_token = hec_token

    async def send_event(self, event: Dict[str, Any]) -> bool:
        import httpx

        payload = {
            "time": event.get("timestamp", time.time()),
            "sourcetype": "shopsquire:security",
            "source": "shopsquire-api",
            "event": event
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.hec_url,
                headers={"Authorization": f"Splunk {self.hec_token}"},
                json=payload
            )
            return response.status_code == 200

    async def send_batch(self, events: List[Dict[str, Any]]) -> int:
        # Splunk HEC supports batch format
        sent = 0
        for event in events:
            if await self.send_event(event):
                sent += 1
        return sent


class ElasticConnector(SecurityTelemetryConnector):
    """Send events to Elasticsearch/Elastic Security"""

    def __init__(self, es_url: str, api_key: str, index: str = "shopsquire-security"):
        self.es_url = es_url
        self.api_key = api_key
        self.index = index

    async def send_event(self, event: Dict[str, Any]) -> bool:
        import httpx

        event["@timestamp"] = event.get("timestamp", time.time()) * 1000

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.es_url}/{self.index}/_doc",
                headers={"Authorization": f"ApiKey {self.api_key}"},
                json=event
            )
            return response.status_code in [200, 201]

    async def send_batch(self, events: List[Dict[str, Any]]) -> int:
        # Use Elasticsearch bulk API
        bulk_body = ""
        for event in events:
            event["@timestamp"] = event.get("timestamp", time.time()) * 1000
            bulk_body += json.dumps({"index": {"_index": self.index}}) + "\n"
            bulk_body += json.dumps(event) + "\n"

        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.es_url}/_bulk",
                headers={
                    "Authorization": f"ApiKey {self.api_key}",
                    "Content-Type": "application/x-ndjson"
                },
                content=bulk_body
            )
            result = response.json()
            return len(events) - len(result.get("errors", []))


class SecurityTelemetryRouter:
    """Route security events to multiple destinations"""

    def __init__(self):
        self.connectors: List[SecurityTelemetryConnector] = []
        self.buffer: List[Dict[str, Any]] = []
        self.buffer_size = 100
        self.flush_interval = 5  # seconds

    def add_connector(self, connector: SecurityTelemetryConnector):
        self.connectors.append(connector)

    async def emit(self, event: Dict[str, Any]):
        """Add event to buffer, flush if full"""
        event["emitted_at"] = time.time()
        self.buffer.append(event)

        if len(self.buffer) >= self.buffer_size:
            await self.flush()

    async def flush(self):
        """Send buffered events to all connectors"""
        if not self.buffer:
            return

        events = self.buffer.copy()
        self.buffer.clear()

        for connector in self.connectors:
            try:
                await connector.send_batch(events)
            except Exception as e:
                # Log error but don't fail
                print(f"Failed to send to {connector.__class__.__name__}: {e}")

    async def start_background_flush(self):
        """Start background task to periodically flush buffer"""
        while True:
            await asyncio.sleep(self.flush_interval)
            await self.flush()
```

### When to Use EDR/XDR vs Internal Monitoring

| Scenario | Internal Monitoring | EDR/XDR Integration |
|----------|--------------------|--------------------|
| Application-layer threats | Primary | Secondary |
| Prompt injection | Primary | Log for correlation |
| API abuse | Primary | Optional |
| Supply chain attacks | Primary detection | Enrichment + response |
| Endpoint compromise | N/A | Primary |
| Network-level attacks | N/A | Primary |
| Lateral movement | Limited | Primary |
| Malware detection | N/A | Primary |
| Compliance evidence | Primary | Supplementary |

**Recommendation:** Your internal monitoring handles application-layer security well. EDR/XDR adds value for:
1. Correlating app events with endpoint/network events
2. Automated response capabilities
3. Threat intelligence enrichment
4. Compliance requirements (some require EDR)

---

## TF-IDF and Anomaly Detection

### When TF-IDF Makes Sense

```
┌─────────────────────────────────────────────────────────────┐
│              TF-IDF USE CASES FOR SECURITY                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  GOOD FIT:                                                  │
│  • Detecting novel attack patterns in logs                 │
│  • Identifying unusual API payloads                        │
│  • Clustering similar security events                      │
│  • Finding anomalous user queries                          │
│                                                             │
│  NOT NEEDED FOR:                                            │
│  • Known attack signatures (use regex)                     │
│  • Structured data anomalies (use statistical methods)     │
│  • Real-time blocking (too slow)                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Implementation

```python
# src/app/security/text_anomaly.py

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from typing import List, Tuple, Optional
import pickle
import os

class TextAnomalyDetector:
    """Detect anomalous text using TF-IDF and cosine similarity"""

    def __init__(self, redis, model_path: str = "models/tfidf_baseline.pkl"):
        self.redis = redis
        self.model_path = model_path
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.baseline_vectors = None
        self._load_model()

    def _load_model(self):
        """Load pre-trained model if exists"""
        if os.path.exists(self.model_path):
            with open(self.model_path, "rb") as f:
                data = pickle.load(f)
                self.vectorizer = data["vectorizer"]
                self.baseline_vectors = data["baseline_vectors"]

    def train_baseline(self, normal_texts: List[str]):
        """Train baseline from known-good texts"""
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 3),
            stop_words="english"
        )

        self.baseline_vectors = self.vectorizer.fit_transform(normal_texts)

        # Save model
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump({
                "vectorizer": self.vectorizer,
                "baseline_vectors": self.baseline_vectors
            }, f)

    def detect_anomaly(
        self,
        text: str,
        threshold: float = 0.3
    ) -> Tuple[bool, float, str]:
        """
        Detect if text is anomalous compared to baseline.
        Returns (is_anomaly, anomaly_score, explanation)
        """

        if self.vectorizer is None or self.baseline_vectors is None:
            return False, 0.0, "no_baseline_trained"

        # Vectorize input
        text_vector = self.vectorizer.transform([text])

        # Calculate similarity to baseline
        similarities = cosine_similarity(text_vector, self.baseline_vectors)
        max_similarity = float(similarities.max())
        avg_similarity = float(similarities.mean())

        # Low similarity = anomalous
        anomaly_score = 1.0 - max_similarity

        is_anomaly = anomaly_score > threshold

        explanation = f"max_sim={max_similarity:.3f}, avg_sim={avg_similarity:.3f}"

        return is_anomaly, anomaly_score, explanation

    def update_baseline_online(self, text: str, is_normal: bool):
        """
        Online learning: update baseline with new example.
        Only add if confirmed normal (human reviewed).
        """
        if not is_normal:
            return

        # Store for batch retraining
        self.redis.lpush("tfidf:training_queue", text)

        # Retrain if queue is large enough
        queue_size = self.redis.llen("tfidf:training_queue")
        if queue_size >= 1000:
            self._retrain_from_queue()

    def _retrain_from_queue(self):
        """Retrain model with queued examples"""
        new_texts = self.redis.lrange("tfidf:training_queue", 0, -1)
        new_texts = [t.decode() if isinstance(t, bytes) else t for t in new_texts]

        if self.baseline_vectors is not None:
            # Get existing training data by inverse transform (approximate)
            # In practice, you'd store original texts
            pass

        self.train_baseline(new_texts)
        self.redis.delete("tfidf:training_queue")
```

### Alternative: Embedding-Based Anomaly Detection

```python
# src/app/security/embedding_anomaly.py

import numpy as np
from typing import List, Tuple
import httpx
import os

class EmbeddingAnomalyDetector:
    """
    Use embeddings for semantic anomaly detection.
    More powerful than TF-IDF for understanding meaning.
    """

    def __init__(self, redis):
        self.redis = redis
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.baseline_embeddings: np.ndarray = None

    async def get_embedding(self, text: str) -> np.ndarray:
        """Get embedding from OpenAI"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.openai_key}"},
                json={
                    "model": "text-embedding-3-small",
                    "input": text
                }
            )
            data = response.json()
            return np.array(data["data"][0]["embedding"])

    async def detect_anomaly(
        self,
        text: str,
        threshold: float = 0.7
    ) -> Tuple[bool, float, str]:
        """Detect anomaly using embedding similarity"""

        if self.baseline_embeddings is None:
            return False, 0.0, "no_baseline"

        embedding = await self.get_embedding(text)

        # Cosine similarity with baseline
        similarities = np.dot(self.baseline_embeddings, embedding) / (
            np.linalg.norm(self.baseline_embeddings, axis=1) * np.linalg.norm(embedding)
        )

        max_sim = float(similarities.max())
        anomaly_score = 1.0 - max_sim

        return anomaly_score > threshold, anomaly_score, f"max_sim={max_sim:.3f}"
```

---

## IAM Monitoring & Logging

### What to Log for IAM

```python
# src/app/security/iam_logger.py

from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum
import time
import json

class IAMEventType(Enum):
    # Authentication
    LOGIN_SUCCESS = "iam.login.success"
    LOGIN_FAILURE = "iam.login.failure"
    LOGOUT = "iam.logout"
    TOKEN_ISSUED = "iam.token.issued"
    TOKEN_REVOKED = "iam.token.revoked"
    TOKEN_REFRESH = "iam.token.refresh"

    # Authorization
    PERMISSION_GRANTED = "iam.permission.granted"
    PERMISSION_DENIED = "iam.permission.denied"
    ROLE_ASSUMED = "iam.role.assumed"

    # Administrative
    USER_CREATED = "iam.user.created"
    USER_DELETED = "iam.user.deleted"
    USER_MODIFIED = "iam.user.modified"
    ROLE_CREATED = "iam.role.created"
    ROLE_MODIFIED = "iam.role.modified"
    API_KEY_CREATED = "iam.apikey.created"
    API_KEY_ROTATED = "iam.apikey.rotated"
    API_KEY_REVOKED = "iam.apikey.revoked"

    # Anomalies
    IMPOSSIBLE_TRAVEL = "iam.anomaly.impossible_travel"
    UNUSUAL_TIME = "iam.anomaly.unusual_time"
    NEW_DEVICE = "iam.anomaly.new_device"
    PRIVILEGE_ESCALATION = "iam.anomaly.privilege_escalation"

@dataclass
class IAMEvent:
    event_type: IAMEventType
    timestamp: float
    actor: str  # User/service performing action
    target: Optional[str]  # User/resource being acted upon
    source_ip: str
    user_agent: Optional[str]
    session_id: Optional[str]
    success: bool
    details: Dict[str, Any]
    risk_score: float = 0.0

class IAMLogger:
    """Log and monitor IAM events"""

    def __init__(self, db, redis, alerter):
        self.db = db
        self.redis = redis
        self.alerter = alerter

    async def log(self, event: IAMEvent):
        """Log IAM event and check for anomalies"""

        # Store in database
        self.db.execute("""
            INSERT INTO iam_events
            (event_type, timestamp, actor, target, source_ip, user_agent,
             session_id, success, details, risk_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_type.value,
            event.timestamp,
            event.actor,
            event.target,
            event.source_ip,
            event.user_agent,
            event.session_id,
            event.success,
            json.dumps(event.details),
            event.risk_score
        ))
        self.db.commit()

        # Check for anomalies
        await self._check_anomalies(event)

        # Update user profile for behavioral analysis
        await self._update_user_profile(event)

    async def _check_anomalies(self, event: IAMEvent):
        """Check for IAM anomalies"""

        # Impossible travel
        if event.event_type in [IAMEventType.LOGIN_SUCCESS, IAMEventType.TOKEN_ISSUED]:
            last_login = await self._get_last_login(event.actor)
            if last_login and self._is_impossible_travel(last_login, event):
                await self.alerter.escalate(
                    severity="high",
                    category="iam_anomaly",
                    message=f"Impossible travel detected for {event.actor}",
                    details={
                        "previous_ip": last_login["source_ip"],
                        "previous_time": last_login["timestamp"],
                        "current_ip": event.source_ip,
                        "current_time": event.timestamp
                    }
                )

        # Multiple failed logins
        if event.event_type == IAMEventType.LOGIN_FAILURE:
            failures = await self._count_recent_failures(event.actor, minutes=15)
            if failures >= 5:
                await self.alerter.escalate(
                    severity="medium",
                    category="iam_anomaly",
                    message=f"Multiple login failures for {event.actor}",
                    details={"failure_count": failures, "window_minutes": 15}
                )

        # Privilege escalation
        if event.event_type in [IAMEventType.ROLE_ASSUMED, IAMEventType.PERMISSION_GRANTED]:
            if self._is_sensitive_permission(event.details.get("permission")):
                await self.alerter.escalate(
                    severity="medium",
                    category="iam_anomaly",
                    message=f"Sensitive permission granted to {event.target or event.actor}",
                    details=event.details
                )

    async def _get_last_login(self, actor: str) -> Optional[Dict]:
        """Get last login for user"""
        row = self.db.execute("""
            SELECT source_ip, timestamp FROM iam_events
            WHERE actor = ? AND event_type = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (actor, IAMEventType.LOGIN_SUCCESS.value)).fetchone()

        return dict(row) if row else None

    def _is_impossible_travel(self, last: Dict, current: IAMEvent) -> bool:
        """Check if travel between logins is physically impossible"""
        time_diff = current.timestamp - last["timestamp"]

        # If same IP, not impossible travel
        if last["source_ip"] == current.source_ip:
            return False

        # Would need GeoIP to calculate actual distance
        # For now, flag if different country within 1 hour
        # (simplified - real implementation would use MaxMind GeoIP)

        return time_diff < 3600  # 1 hour

    async def _count_recent_failures(self, actor: str, minutes: int) -> int:
        """Count login failures in time window"""
        since = time.time() - (minutes * 60)
        row = self.db.execute("""
            SELECT COUNT(*) as count FROM iam_events
            WHERE actor = ? AND event_type = ? AND timestamp > ?
        """, (actor, IAMEventType.LOGIN_FAILURE.value, since)).fetchone()

        return row["count"] if row else 0

    def _is_sensitive_permission(self, permission: Optional[str]) -> bool:
        """Check if permission is sensitive"""
        sensitive = [
            "admin", "owner", "delete", "billing",
            "api_key", "security", "compliance"
        ]
        if not permission:
            return False
        return any(s in permission.lower() for s in sensitive)

    async def _update_user_profile(self, event: IAMEvent):
        """Update user behavioral profile"""
        profile_key = f"iam:profile:{event.actor}"

        # Track login times, IPs, user agents
        profile = self.redis.hgetall(profile_key)

        if event.event_type == IAMEventType.LOGIN_SUCCESS:
            # Track login hour distribution
            hour = time.strftime("%H", time.localtime(event.timestamp))
            self.redis.hincrby(profile_key, f"login_hour:{hour}", 1)

            # Track known IPs
            self.redis.sadd(f"iam:known_ips:{event.actor}", event.source_ip)

            # Track devices (by user agent hash)
            if event.user_agent:
                import hashlib
                ua_hash = hashlib.sha256(event.user_agent.encode()).hexdigest()[:16]
                self.redis.sadd(f"iam:known_devices:{event.actor}", ua_hash)

        self.redis.expire(profile_key, 86400 * 90)  # 90 day retention
```

### IAM Events Dashboard Panel

```json
{
  "title": "IAM Activity Monitor",
  "type": "table",
  "gridPos": {"h": 8, "w": 24, "x": 0, "y": 24},
  "targets": [
    {
      "rawSql": "SELECT timestamp, event_type, actor, source_ip, success, risk_score FROM iam_events ORDER BY timestamp DESC LIMIT 100",
      "format": "table"
    }
  ],
  "fieldConfig": {
    "overrides": [
      {
        "matcher": {"id": "byName", "options": "success"},
        "properties": [
          {
            "id": "custom.displayMode",
            "value": "color-background"
          },
          {
            "id": "mappings",
            "value": [
              {"type": "value", "options": {"true": {"color": "green"}}},
              {"type": "value", "options": {"false": {"color": "red"}}}
            ]
          }
        ]
      }
    ]
  }
}
```

---

## Privacy vs Security Balance

### The Right Balance

```
┌─────────────────────────────────────────────────────────────┐
│                 PRIVACY vs SECURITY SPECTRUM                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  More Privacy ◄────────────────────────────► More Security  │
│                                                             │
│  • Log nothing          • Log everything                    │
│  • No monitoring        • Full surveillance                 │
│  • User anonymity       • User attribution                  │
│  • Short retention      • Indefinite retention              │
│                                                             │
│  YOUR SWEET SPOT:                                           │
│  ─────────────────                                          │
│  • Log security-relevant events (not all activity)          │
│  • Hash/pseudonymize user IDs in logs                       │
│  • 90-day retention for most logs, 7 days for PII          │
│  • Aggregate metrics, detailed logs only on anomaly        │
│  • Consent-based extended monitoring for investigations    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### What to Log vs What to Skip

| Data Type | Log? | How |
|-----------|------|-----|
| Security events | Yes | Full details, sanitized PII |
| API requests | Aggregate only | Count/latency, not payload |
| User queries | Hash only | SHA256 of query, not content |
| Failed auth | Yes | IP, timestamp, hashed user ID |
| Successful auth | Yes | IP, timestamp, hashed user ID |
| Admin actions | Yes | Full audit trail |
| Payment data | Never | Use tokenization |
| Session content | Aggregate | Word count, not content |
| IP addresses | Hash for EU | Full for security events |

### Privacy-Preserving Security Monitoring

```python
# src/app/security/privacy_aware_logger.py

import hashlib
from typing import Dict, Any
import time

class PrivacyAwareSecurityLogger:
    """Log security events while preserving user privacy"""

    def __init__(self, db, is_gdpr_user_fn):
        self.db = db
        self.is_gdpr_user = is_gdpr_user_fn

    def log_event(
        self,
        event_type: str,
        user_id: str,
        ip_address: str,
        details: Dict[str, Any]
    ):
        """Log security event with privacy controls"""

        # Check if user is in GDPR jurisdiction
        gdpr_applies = self.is_gdpr_user(user_id)

        # Prepare privacy-aware record
        record = {
            "event_type": event_type,
            "timestamp": time.time(),
            "user_id_hash": self._hash_if_gdpr(user_id, gdpr_applies),
            "ip_hash": self._hash_if_gdpr(ip_address, gdpr_applies),
            "details": self._sanitize_details(details, gdpr_applies)
        }

        # Store with appropriate retention
        retention_days = 7 if gdpr_applies else 90

        self.db.execute("""
            INSERT INTO security_events_privacy
            (event_type, timestamp, user_id_hash, ip_hash, details, retention_until)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record["event_type"],
            record["timestamp"],
            record["user_id_hash"],
            record["ip_hash"],
            record["details"],
            time.time() + (retention_days * 86400)
        ))

    def _hash_if_gdpr(self, value: str, gdpr_applies: bool) -> str:
        """Hash value if GDPR applies"""
        if gdpr_applies:
            return hashlib.sha256(value.encode()).hexdigest()[:16]
        return value

    def _sanitize_details(self, details: Dict[str, Any], gdpr_applies: bool) -> str:
        """Remove PII from details if GDPR applies"""
        import json
        import re

        details_str = json.dumps(details)

        if gdpr_applies:
            # Remove emails
            details_str = re.sub(
                r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
                '[EMAIL_REDACTED]',
                details_str
            )
            # Remove phone numbers
            details_str = re.sub(
                r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
                '[PHONE_REDACTED]',
                details_str
            )

        return details_str
```

### You're NOT Being Paranoid

This level of security thinking is:
- **Expected** for systems handling payments
- **Required** for SOC 2 compliance
- **Standard** at security-mature companies
- **Valuable** differentiator for enterprise sales

What would be paranoid:
- Logging all user keystrokes
- Storing conversation content indefinitely
- Tracking users across devices without consent
- Implementing surveillance beyond security needs

---

## Vendor Comparison

### How Your Approach Compares

| Feature | Your Implementation | Auth0 | Okta | AWS IAM | Datadog Security |
|---------|-------------------|-------|------|---------|------------------|
| Custom agent monitoring | ✓ Custom | ✗ | ✗ | ✗ | Partial |
| Supply chain detection | ✓ Custom | ✗ | ✗ | Partial | ✗ |
| LLM security | ✓ Custom | ✗ | ✗ | ✗ | ✗ |
| MCP tool monitoring | ✓ Custom | ✗ | ✗ | ✗ | ✗ |
| Human escalation | ✓ Custom | ✗ | ✗ | ✗ | Partial |
| RBAC | ✓ Basic | ✓ Full | ✓ Full | ✓ Full | N/A |
| SSO/SAML | ✗ Missing | ✓ Full | ✓ Full | ✓ Full | N/A |
| MFA | ✗ Missing | ✓ Full | ✓ Full | ✓ Full | N/A |
| Threat intelligence | Partial | ✗ | ✗ | ✗ | ✓ Full |

### What You Have That Vendors Don't

1. **Agentic Security** - No vendor monitors AI agent behavior
2. **Supply Chain for APIs** - Custom baseline/anomaly detection
3. **MCP Tool Security** - Novel category, no vendor coverage
4. **LLM-Specific Threats** - Prompt injection, jailbreak detection
5. **Human-in-the-Loop** - Approval queue for uncertain decisions

### What Vendors Have That You Could Add

1. **SSO/SAML** - Consider integrating Auth0 or Okta
2. **MFA** - Add TOTP or WebAuthn
3. **Threat Intelligence Feeds** - Subscribe to commercial feeds
4. **Managed SIEM** - Splunk Cloud, Elastic Cloud, Datadog
5. **Compliance Automation** - Vanta, Drata, Secureframe

### Recommended Hybrid Approach

```
┌─────────────────────────────────────────────────────────────┐
│                    HYBRID SECURITY STACK                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  YOUR CUSTOM LAYER (Keep)                                   │
│  ───────────────────────                                    │
│  • Agent behavior monitoring                                │
│  • Supply chain detection                                   │
│  • MCP tool security                                        │
│  • LLM threat detection                                     │
│  • Human escalation framework                               │
│  • Application-specific RBAC                                │
│                                                             │
│  VENDOR LAYER (Add)                                         │
│  ──────────────────                                         │
│  • Auth0/Okta: SSO, MFA, user management                   │
│  • CrowdStrike/SentinelOne: Endpoint protection            │
│  • Datadog/Splunk: Log aggregation, correlation            │
│  • Vanta: Compliance automation                            │
│                                                             │
│  INTEGRATION POINTS                                         │
│  ──────────────────                                         │
│  • Stream events to SIEM                                    │
│  • Submit IOCs to EDR                                       │
│  • Pull threat intel feeds                                  │
│  • Export compliance evidence                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Portfolio Showcase Guide

### How to Present This to Hiring Managers

#### 1. Executive Summary Pitch

> "I built an AI-native security monitoring system for an agentic e-commerce platform. It detects supply chain attacks on third-party APIs, monitors LLM tool invocations for prompt injection, and provides human-in-the-loop escalation for uncertain threats. The system integrates with Prometheus/Grafana for observability and can stream to enterprise SIEMs."

#### 2. Key Talking Points

**For Security Engineer Roles:**
- "I implemented OWASP LLM Top 10 detection including prompt injection variants"
- "Supply chain security with API response baselining and anomaly detection"
- "Human escalation framework with confidence-based routing"
- "Privacy-preserving logging that handles GDPR requirements"

**For Platform/Infrastructure Roles:**
- "Designed observability pipeline from app metrics to Grafana dashboards"
- "Built circuit breaker patterns for graceful degradation"
- "Implemented webhook security with signature verification and replay protection"
- "Created IAM event logging with behavioral anomaly detection"

**For AI/ML Engineering Roles:**
- "Built security guardrails for autonomous AI agents"
- "Implemented TF-IDF-based anomaly detection for unknown attack patterns"
- "Designed human-in-the-loop approval system for high-risk AI decisions"
- "Created output validation to prevent AI hallucination (SKU invention)"

#### 3. Demo Walkthrough Structure

```
1. THREAT DETECTION (5 min)
   - Show security_observer analyzing request
   - Demonstrate prompt injection detection
   - Show MITRE ATT&CK mapping

2. SUPPLY CHAIN MONITORING (5 min)
   - Show API baseline establishment
   - Trigger anomaly detection
   - Demonstrate webhook signature validation

3. HUMAN ESCALATION (5 min)
   - Show event flowing to review queue
   - Demonstrate approval workflow
   - Show Slack notification integration

4. OBSERVABILITY (5 min)
   - Walk through Grafana dashboards
   - Show Prometheus metrics
   - Demonstrate alert firing

5. PRIVACY CONTROLS (3 min)
   - Show PII redaction in logs
   - Demonstrate GDPR-aware logging
   - Show data retention policies
```

#### 4. GitHub README Structure

```markdown
# ShopSquire Security Architecture

## Overview
AI-native security monitoring for agentic systems.

## Features
- 🛡️ Supply chain attack detection
- 🤖 LLM/Agent behavior monitoring
- 🔧 MCP tool security
- 👤 Human-in-the-loop escalation
- 📊 Prometheus/Grafana observability
- 🔒 GDPR-compliant logging

## Architecture
[Insert diagram]

## Quick Start
```bash
docker-compose up -d
open http://localhost:3000  # Grafana
```

## Security Capabilities
### Threat Detection
- OWASP LLM Top 10
- Prompt injection variants
- Supply chain anomalies

### Monitoring
- API response baselining
- Webhook signature verification
- IAM behavioral analysis

## Documentation
- [Security Architecture](docs/SECURITY_AGENT_MONITORING_ARCHITECTURE.md)
- [Threat Model](docs/THREAT_MODEL.md)
- [Runbooks](docs/RUNBOOKS.md)
```

#### 5. Interview Questions to Prepare For

| Question | Your Answer Framework |
|----------|----------------------|
| "Why build custom vs use vendor?" | "Vendors don't cover AI agent security. Custom for novel threats, vendor for commodity features." |
| "How do you handle false positives?" | "Confidence scoring + human review queue. Auto-escalate high confidence, queue low confidence for human decision." |
| "What about scale?" | "Prometheus handles metrics at scale. Event buffering + batch writes. Redis for real-time, Postgres for persistence." |
| "Privacy vs security trade-off?" | "Log security-relevant data only. Hash PII for GDPR users. Aggregate metrics, detailed logs only on anomaly." |
| "How would you improve it?" | "Add ML-based anomaly detection, integrate threat intel feeds, implement SOAR automation." |

#### 6. Metrics to Highlight

```
• Detection coverage: OWASP LLM Top 10, MITRE ATT&CK
• Response time: <100ms threat analysis
• False positive rate: Human review queue prevents blocking legitimate traffic
• Compliance: GDPR-aware logging, SOC 2 audit trail
• Observability: 15+ custom Prometheus metrics, 4 Grafana dashboards
```

#### 7. What Makes This Impressive

1. **Novel Problem Space** - AI agent security is cutting-edge
2. **Defense in Depth** - Multiple detection layers
3. **Production Thinking** - Observability, escalation, compliance
4. **Balance** - Security without breaking UX or privacy
5. **Integration Ready** - Can connect to enterprise tools

---

## Summary: Are You Paranoid?

**No. You're thinking like a senior security engineer.**

The approach of "detect and escalate" is:
- **Industry standard** for security operations
- **Appropriate** for payment/PII handling systems
- **Scalable** (human review only for uncertain cases)
- **Compliant** (audit trail, GDPR awareness)
- **Impressive** to hiring managers

What you should **add**:
- EDR/XDR integration for endpoint visibility
- Threat intel feeds for known bad indicators
- SSO/MFA via established vendor

What you should **not** add:
- Auto-blocking without human review
- Indefinite retention of all data
- Surveillance beyond security scope

Your security architecture is **portfolio-worthy** and demonstrates the kind of systems thinking that security-conscious companies look for.

---

*This document serves as both implementation guide and portfolio piece.*
