"""recommendation_core — the V2 brain (Phase 4 of docs/SHOPSQUIRE_V2_GREENFIELD_ROADMAP).

A CLEAN orchestrator that imports proven leaf services — deliberately NOT grown out of
recommend_pipeline.py (GPT-5.6 architecture ruling: untyped dicts, legacy retriever, no
tenant scope, fraud fail-open; its bounded fan-out is reused as a utility only).

Target shape:
    request → typed TurnEnvelope → model proposes bounded intent/taxonomy/tool plan
    → deterministic plan validator → tenant-scoped catalog/inventory evidence
    (catalog_read_model) → normalized attribute + workload fit (attribute_registry)
    → deterministic commerce/security gates → model-grounded explanation
    → unified CoreResponse → legacy response adapter (fork emulation)

Build order (status doc §4): envelope + legacy_adapter FIRST, contract-tested against the
frozen suggest_contract and the recorded corpus — the boundary exists before any brain code.
Acceptance: the corpus's 3 known_wrongs pass their expect_v2 assertions with zero BLOCKERs
on the parity cases (recommend_parity_full.summarize_run gates).
"""
