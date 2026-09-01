# Pending official-source origin review packet

Prepared: 2026-09-01 (Australia/Sydney)

Status: **independent review required**. This packet is operational evidence,
not an approval. Every source below remains `pending_independent_human_review`
until a named reviewer records an approve/reject decision, timestamp and basis
in `config/official_workload_sources.json`.

## Reviewer protocol

For each source, independently confirm:

1. the registrable domain is controlled by the stated publisher;
2. the entry point is the publisher's applicable documentation surface;
3. allowed claims do not exceed the stated scope;
4. forbidden claims cannot enter product-fit, price, availability or commerce authority;
5. parser and freshness policy are appropriate;
6. redirects remain on an approved publisher-controlled domain;
7. interactive or identity-bound pages do not imply reusable public evidence.

Record `review_status`, `reviewed_at`, `reviewed_by`, and `review_basis` only
after completing those checks. A reachable page is not proof of ownership,
semantic applicability or claim correctness.

## Origin inventory and 2026-09-01 reachability observation

| Source | Publisher | Scope | SLA | HTTP observation | Reviewer decision |
|---|---|---|---:|---|---|
| `gns3_official_docs` | GNS3 | GNS3/GNS3 VM host requirements only | 168 h | 200, canonical URL retained | Pending |
| `huggingface_official_docs_and_model_cards` | Hugging Face or verified model publisher | Named framework docs and verified model-card revision | 72 h | 200, canonical URL retained | Pending; model-card publisher identity needs special review |
| `nolvus_official_docs` | Nolvus | Named Nolvus modlist requirements only | 168 h | 200, canonical URL retained | Pending |
| `ubuntu_certified_laptops` | Canonical | Exact listed hardware configuration and Ubuntu release | 720 h | 200, canonical URL retained | Pending |
| `lenovo_accessory_compatibility` | Lenovo | Exact machine-type/accessory/display compatibility rows | 720 h | 403 to an unauthenticated HEAD request | Pending; establish an approved fetch method before enrolment |
| `microsoft_windows_enterprise_lifecycle` | Microsoft | Published Enterprise lifecycle and management compatibility | 168 h | 200, canonical URL retained | Pending |
| `lenovo_product_security_advisories` | Lenovo PSIRT | Advisories explicitly naming an exact product/component | 24 h | 403 to an unauthenticated HEAD request | Pending; establish an approved fetch method before enrolment |
| `hp_warranty_status` | HP | Exact serial/product/region warranty status | 24 h | 200, canonical URL retained | Pending; interactive and potentially identity-bound |

## Mandatory scope caveats

- Hugging Face community model cards are not authoritative merely because they
  are hosted on `huggingface.co`; publisher identity and revision must match.
- Ubuntu certification applies only to the exact configuration and Ubuntu
  release listed. It is not a general Linux compatibility claim.
- Lenovo compatibility and PSIRT absence must never be interpreted as evidence
  of compatibility or safety.
- HP warranty results are serial-, product- and region-bound and must not be
  cached or generalized to a product family.
- None of these origins establishes price, stock, exact product fit, cart,
  supplier RFQ or payment authority.

## Sign-off record

| Source | Approve / reject | Reviewer | UTC timestamp | Evidence/basis |
|---|---|---|---|---|
| `gns3_official_docs` |  |  |  |  |
| `huggingface_official_docs_and_model_cards` |  |  |  |  |
| `nolvus_official_docs` |  |  |  |  |
| `ubuntu_certified_laptops` |  |  |  |  |
| `lenovo_accessory_compatibility` |  |  |  |  |
| `microsoft_windows_enterprise_lifecycle` |  |  |  |  |
| `lenovo_product_security_advisories` |  |  |  |  |
| `hp_warranty_status` |  |  |  |  |

