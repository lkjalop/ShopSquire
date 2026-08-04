# Competitive Delta, Adtech/Network-BI, and Poison-Resistant Agents — Strategic Assessment

**Date:** 2026-07-01. Grounded in a 2-agent code audit (network/adtech baseline + agent-learning/poisoning
posture). Answers: what do competitor/adjacent platforms do that we should bridge; how do we do better on
digital-marketing metrics + network/endpoint intel (ASN/GeoIP/CDN/unique-visits) for BI + 3rd-party
enrichment; and how do we improve the agents from ecommerce-AI research while resisting poisoning.

## The thesis (one line)

Don't out-Shopify Shopify. Our moat is **security-grade network intelligence + a governed agent-learning
skeleton that pure commerce/marketing platforms don't have.** The play is **REPURPOSE** (network intel →
marketing BI; agent governance → trustworthy adaptive agents), **BRIDGE** competitor deltas via connectors
(not rebuilds), and make **poison-resistant adaptive agents** a first-class differentiator.

## 1. Competitor delta — where we win/lose and how to bridge

| Platform | What they own | Our delta (gap) | Bridge |
|---|---|---|---|
| **Shopify** (+ Magic/Sidekick) | Commerce OS: storefront, checkout, payments, app ecosystem, native analytics | They own the storefront + payments; we're the intelligence + security layer ON TOP. We lack native storefront/checkout. | **Connector, not replacement** (`erp/connectors/shopify` exists, procurement-oriented). Add a marketing-data + storefront-experience connector. |
| **Intercom (Fin)** | Best-in-class support-AI, resolution analytics, CSAT attribution | Their support-AI resolution loop + objection→answer execution vs our escalation room. Our M5 support-phrasing execution is shadow-only. | Support-signal ingestion + objection→guidance **execution** (the M5 support surface) + a support connector. |
| **Agentforce (Salesforce)** | Enterprise agent orchestration, Data Cloud unification, guardrails, observability | We MATCH on the audit/gate/reversibility story (arguably lead on transparency); we LAG on CRM depth + connectors + data unification at enterprise scale. | Lean into the governance/observability lead; add CRM/Data-Cloud connectors. |
| **GA4 / Segment / Klaviyo (CDP)** | Identity resolution, unique-visitor + traffic-source analytics, audience segments, campaign attribution | **The real gap you pointed at** — they own marketing BI; we compute *richer network-grade signals* but never surface them for BI, and we have **zero traffic-source attribution**. | Repurpose our network intel + add UTM/referrer capture (§2). This is where we can *leapfrog*, not catch up. |
| **Cloudflare (edge/audience)** | Edge network signals, bot management, ASN/geo audience | We compute comparable per-request ASN/VPN/Tor/impossible-travel — but for fraud only. | Repurpose as bot-clean visitor + audience signals (§2). |

## 2. Digital-marketing / adtech / network-intel — the standout opportunity

**What we HAVE (security-grade, computed on every event, wired ONLY to fraud):** ASN + ASN-org, GeoIP country,
hosting/VPN/Tor flags, JA3/JA4 TLS fingerprint (ingested from edge), IP velocity / impossible-travel,
behavioral-biometric bot-likelihood, and a per-event network row persisted in `security_event_ingest`
(`geo_country, asn, asn_org, is_vpn, is_hosting, is_tor, geo_risk, impossible_travel`). Clickstream (path,
dwell_ms, session_hash, device_hash, asn, country) is **ingested but write-only** (`event_log`), never mined.

**What we LACK (verified absent):**
- **Traffic-source / campaign attribution — the #1 gap.** No `utm_*`, `gclid`, `fbclid`, or `referrer` capture
  anywhere. The `detect_channel_performance` / `detect_segment_shift` detectors EXIST but nothing feeds
  `channel`/`segment` a real source.
- Unique-visitor dedup / sessionization; bounce / pageview funnel; UA→device-class parsing; CDN detection;
  a `/marketing/` analytics namespace (everything geo/network lives under `/fraud/` or `/security/`).

**The repurposing plays (mostly no-secrets — a repurpose + last-mile-ingest, not a from-scratch build):**
1. **UTM/referrer/gclid capture at the `consumer_signals` ingest** → lights up the already-built
   `channel_performance`/`segment_shift` detectors + the attribution backbone, converting "which recommendation
   drove the order" into "which **campaign/channel** drove the order." **Highest-leverage single change.**
2. **"Verified-human visits."** Apply the already-computed `is_hosting/is_vpn/is_tor` + impossible-travel flags
   to the ingested clickstream → a bot-clean visitor metric most SMB analytics can't produce. A network-grade
   BI headline using code that already exists.
3. **`/marketing/` namespace** surfacing ASN/ISP/geo as audience dimensions (a second consumer of
   `geoip.enrich_ip()` + a role/label change — zero new computation).
4. **Partner/supplier BI enrichment** via the existing webhook dispatcher + PowerBI read-path: an *aggregated,
   hashed* audience view (top ASNs, country mix, human-vs-bot ratio, funnel drop by geo) shared with a
   supplier/partner's BI — a security byproduct turned into a shared business signal.

**Privacy / compliance (must-state):** raw IP is deliberately dropped after ASN/country derivation (keep it that
way). Reusing a fraud signal for **marketing/audience** is a GDPR/CCPA/APP **purpose change** needing its own
consent basis + purpose-limitation note. Route any 3rd-party audience export through the existing
`contact_governance` / `privacy.py` / `dlp_export` rails, never around them.

## 3. Poison-resistant adaptive agents — the trust differentiator

**The good news:** the learning loops (ranking nudge, market-intel shadow/live, LinUCB bandit, attribution
reward feed, human-correction priors) are **default-OFF, env-gated, funnelled through one
`adaptive_action_gate` chokepoint, reversible, and audited.** The ranking nudge is exemplary (canary +
kill-switch + reversible delta + durable audit). This governance-of-the-feedback-loop is itself a
differentiator vs Agentforce/Intercom.

**The real risks (grounded):**
1. **Search-query → "unmet demand" finding → LLM narration (HIGHEST, buyer-reachable).** A query searched ≥3×
   with zero results becomes a `critical`/`warn` finding whose **raw query string** becomes the finding
   `summary`, which in `live` mode flows into other users' LLM narration preamble. Search trust is 0.8 and
   ingest `min_trust=0` → **not quarantined**. An attacker scripts a nonsense query → attacker-chosen text in
   other users' LLM context. (`market_analysis.py:140/157`, `market_intelligence_agent.py:67`.)
2. **Citation-memory loop is BROKEN** — `verify_claim` is never called, so agent trust sits at the 0.5 neutral
   default forever while still feeding security-swarm vote weights + orchestrator context. It influences
   decisions but never learns. (`citation_memory.py:128` unwired.)
3. **Confidence gate is off by default** (`ADAPTIVE_MIN_CONFIDENCE=0.0`) — the "minimum confidence before an
   action" is a no-op until calibrated.
4. **No poisoning red-team** — ATLAS `AML.T0043` is mapped (`atlas_map.py`) but never adversarially tested
   against the feedback loops.
5. Fake-conversion (Sybil-defeats the per-uid cap) + competitor-feed manipulation (trust 0.6, no floor) —
   contained by default-off + settled-order gate, but no trust floor at ingest.

**The research-grade "improve while resisting poison" program (grounded in the gaps):**
- **Provenance-weighted feedback + trust floor:** thread `market_signal.trust_score` + `human_feedback.weight`
  into `reward_from_outcome` and finding severity; enforce `min_trust > 0` at ingest for `demand`/`competitor`.
- **Close the citation loop + trust-decay:** call `verify_claim` from the attribution settle path; decay unverified
  trust to neutral.
- **Anomaly-gate the feedback loop:** gate `detect_inventory_demand_mismatch` on **distinct-uid count**, not raw
  search count; reuse the `escalation_rate_guardrail` pattern on feedback-rate deltas.
- **Sanitize + provenance-tag LLM-visible findings:** run the query string through the existing
  `jailbreak_embedding_guard` before it becomes a narration `summary`; show a provenance chip.
- **Canary/holdout on findings + set a non-zero confidence floor** (extend the ranking-nudge discipline to the
  market-intel `live` path).
- **HITL on high-influence signals** (a single signal that flips a `critical` finding routes to the escalation
  room — rails already exist).
- **AML.T0043 red-team corpus** under `security/redteam/` (fake-review, Sybil-conversion, search-flood,
  return-bomb, competitor-spoof) with precision/recall like `prompt_injection_eval.py`, run in CI per loop.

This makes "adaptive AI agents you can trust because the **feedback loop itself** is governed + red-teamed" a
concrete, defensible differentiator.

## 4. Prioritized bridge roadmap

**P0 — no secrets, closes a real gap/bug, high leverage:**
- **UTM/referrer/gclid capture** → attribution + channel/segment detectors (the marketing-BI foundation).
- **Search-query→finding poisoning fix** (trust floor + distinct-uid gate + sanitize) — an actual live-path
  vulnerability, not just a hardening nicety.
- **Close the citation `verify_claim` loop** (dead code that feeds vote weights).

**P1 — no secrets, differentiators:**
- Verified-human visits + `/marketing/` namespace (repurpose network intel).
- Provenance-weighted reward + set `ADAPTIVE_MIN_CONFIDENCE`.
- AML.T0043 poisoning red-team corpus.

**P2 — connector / secrets-gated:**
- CDP/GA4/Segment + competitor/ad-spend feeds; partner BI export; Intercom/Shopify marketing connectors;
  M5 support-phrasing execution.

## Recommendation

Start with the two P0 items that are **both no-secrets and close a real gap/bug**: (1) UTM/referrer/attribution
capture (unlocks the entire marketing-BI story + feeds detectors already built), and (2) the search-query→finding
poisoning fix (a genuine live-path vulnerability the audit surfaced). Together they advance *both* halves of the
question — better marketing/BI metrics AND more trustworthy agents — with no external dependencies.
