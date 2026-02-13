# 3‑Minute Video Script — ShopSquire Security Demo

## 0:00–0:15 — Intro
- Line: "I built an agentic AI security platform. In 3 minutes, I’ll show three attacks blocked and a live decision trace you can audit."
- Visual: Split screen: terminal (left), dashboard (right).

## 0:15–0:45 — Setup glance
- Line: "Backend on 8080, frontend on 5173, logs tailing WORM audit in real time."
- Visual: `uvicorn` running; `Get-Content runs/audit_worm.log -Wait` tailing; dashboard open at Security.

## 0:45–1:20 — Lane 1: Prompt Injection
- Action: Post CV payload with hidden jailbreak text.
- Visual: Terminal response shows signals: `prompt_injection`/`tool_abuse`/`data_exfiltration`; dashboard event appears; WORM line appended.
- Hook: "Weaponized resume blocked before any model ran."

## 1:20–1:55 — Lane 2: Email BEC / Ransomware
- Action: Post spoofed invoice email (SPF/DKIM/DMARC fail, wire‑fraud language).
- Visual: Verdict `QUARANTINE` + step‑up approval; IOC extraction visible.
- Hook: "Fake invoice never reached accounts payable."

## 1:55–2:30 — Lane 3: Supply‑Chain Poisoning
- Action: Send vendor webhook with schema drift + XSS/eval.
- Visual: Drift alert; auto‑quarantine; per‑tenant isolation noted.
- Hook: "Compromised supplier isolated in seconds; no lateral movement."

## 2:30–2:50 — Evidence & Trace
- Action: Show bi‑temporal decision trace; scoring weights; versions.
- Visual: `/api/v1/trace_debug/latest` JSON; WORM tail; compliance mapping page.
- Line: "What the AI knew, when it decided—frozen and auditable."

## 2:50–3:00 — Close
- Line: "Agents triage in seconds; humans approve what matters. Internal review first, then share externally for feedback."
- Visual: Deck slide with outcomes; contact CTA.
