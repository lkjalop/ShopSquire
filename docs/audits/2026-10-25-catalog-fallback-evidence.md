# Catalogue fallback and cart fixture evidence

The independently assembled public repair branch plus four narrowly selected files passed **44 tests, zero failures, errors or skips**. The selection contains `test_turn_router_clarification.py`, `test_recommend_followup_memory.py` and `test_cart_mutations_endpoint.py`. Changed-file Ruff passed. This is focused qualification, not full-release green.

The unavailable-model fallback now shares the case-intake literal purchase-category boundary. A clearly unsold chair/desk or medical purchase may report off-catalogue; workload words, excluded categories, and a sold gaming-laptop category cannot grant that refusal. Tenant sellability remains authoritative. The gaming-laptop positive control reproduced the regression before the related-category check was added; no prior behavioural expectation was weakened.

The cart endpoint fixture now gives request and trace-worker transactions independent file-backed SQLite connections through the canonical engine factory. Its previous StaticPool shared a single connection, allowing unrelated worker rollback to interfere with a request. Existing application assertions remain unchanged. Broad-suite reproducibility remains a separate gate.

Private native receipt: `implementation-20261024-catalog-independent-v1`, 37.406 seconds, no resource violation. The staged manifest records exact prepared file hashes. No supplier, payment or external mail effect was exercised.
