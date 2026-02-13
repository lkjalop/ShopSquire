# ShopSquire Security Mapping Matrix (Feb 2, 2026)

This is a compact, implementation‑based view of what is currently mapped or detected by the Security Observer and where it appears in decision trace payloads.

## OWASP LLM Top 10

| ID | Name | Signal(s) | Status | Primary Source |
|---|---|---|---|---|
| LLM01 | Prompt Injection | prompt_injection, jailbreak | Implemented | `src/app/security/observer.py` |
| LLM02 | Insecure Output Handling | unicode_obfuscation (heuristic) | Partial | `src/app/security/observer.py` |
| LLM03 | Training Data Poisoning | training_poisoning | Implemented (heuristic) | `src/app/security/observer.py` |
| LLM04 | Model DoS | model_dos | Implemented (heuristic) | `src/app/security/observer.py` |
| LLM05 | Supply Chain | supply_chain | Implemented | `src/app/security/observer.py` |
| LLM06 | Sensitive Info Disclosure | pii, pci, api_key, data_exfiltration | Implemented | `src/app/security/observer.py` |
| LLM07 | Insecure Plugin Design | plugin_insecure | Implemented (heuristic) | `src/app/security/observer.py` |
| LLM08 | Excessive Agency | agentic_tool_abuse | Implemented | `src/app/security/observer.py` |
| LLM09 | Overreliance | overreliance | Implemented (heuristic) | `src/app/security/observer.py` |
| LLM10 | Vector/Embedding Weakness | embedding_weakness | Implemented (heuristic) | `src/app/security/observer.py` |

## OWASP Agentic Top 10 (draft)

| ID | Name | Signal(s) | Status | Primary Source |
|---|---|---|---|---|
| ASI01 | Agent Goal Hijack | prompt_injection, jailbreak | Implemented | `src/app/security/observer.py` |
| ASI02 | Tool Misuse | agentic_tool_abuse | Implemented | `src/app/security/observer.py` |
| ASI03 | Identity/Privilege Abuse | identity_abuse | Implemented (heuristic) | `src/app/security/observer.py` |
| ASI04 | Agentic Supply Chain | supply_chain | Implemented | `src/app/security/observer.py` |
| ASI05 | Unexpected Code Execution | unexpected_code_exec | Implemented (heuristic) | `src/app/security/observer.py` |
| ASI06 | Memory/Context Poisoning | unicode_obfuscation | Implemented (heuristic) | `src/app/security/observer.py` |
| ASI07 | Insecure Inter‑Agent Comms | data_exfiltration | Implemented (heuristic) | `src/app/security/observer.py` |
| ASI08 | Cascading Failures | cascading_failure | Implemented (heuristic) | `src/app/security/observer.py` |
| ASI09 | Human‑Agent Trust Exploitation | authority_impersonation, social_engineering | Implemented | `src/app/security/observer.py` |
| ASI10 | Rogue Agents | rogue_agent | Implemented (heuristic) | `src/app/security/observer.py` |

## MITRE ATLAS

- Implemented tags: `AML.T0043`, `AML.T0015`, `AML.T0048`.
- Mappings in `src/app/security/observer.py`.

## STRIDE

- Implemented tags: `InformationDisclosure`, `Tampering`, `ElevationOfPrivilege`.
- Mappings in `src/app/security/observer.py`.

## DREAD

- Implemented weighted scoring via `config/security/taxonomy/dread_weights.json`.

## PASTA

- Placeholder stage inference added to security details as `pasta_stage`.
- No full PASTA workflow orchestration exists yet.

## PCI‑DSS

- Detection via `src/app/security/pci.py`.
- Enforcement in payments/incident routes; logs in decision trace as PCI signal.

## Supply Chain

- LLM/provider checks in `src/app/security/supply_chain.py`.
- CV supply‑chain indicators in `src/app/services/supply_chain_cv.py`.

## GeoIP/ASN (hashed IP only)

- Hash only (`ip_hash`) + optional enrichment from `config/security/geoip_overrides.json`.
- No raw IP stored in trace payloads.

## Kernel / eBPF

- Not implemented. This requires external host telemetry and an ingestion endpoint.

---

## Trace visibility

Decision trace UI uses:
- `GET /api/v1/decisions/{trace_id}`
- `GET /api/v1/trace/{trace_id}/timeline`

The security observer results show up under the `security_scan` event and the `policy_verdict` event when triggered.
