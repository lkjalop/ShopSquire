# Pytest 30-Test Suite (Comprehensive)

Goal: a runnable, security-first suite covering agents, security observer, context rot, and core commerce flows.

## How to run
```bash
poetry run pytest -q
```

## Test list

### Security: OWASP LLM Top 10 + Prompt Injection
1. `tests/test_security_llm_top10.py::test_security_detects_unicode_prompt_injection` (implemented)
2. `tests/test_security_llm_top10.py::test_security_detects_pii_and_redacts` (implemented)
3. `tests/test_security_prompt_injection_endpoints.py::test_prompt_injection_logged_on_recommend` (implemented)
4. `tests/test_security_prompt_injection_endpoints.py::test_prompt_injection_logged_on_support` (implemented)
5. `tests/test_security_indirect_prompt_injection.py::test_indirect_prompt_injection_from_catalog` (implemented)
6. `tests/test_security_jailbreak_patterns.py::test_jailbreak_keyword_patterns` (implemented)
7. `tests/test_security_pci_detection.py::test_pci_detection_triggers_llm06` (implemented)
8. `tests/test_security_event_tags.py::test_event_has_mitre_and_owasp_tags` (implemented)
9. `tests/test_security_observer_paths.py::test_observer_logs_for_recommend` (implemented)
10. `tests/test_security_observer_paths.py::test_observer_logs_for_support` (implemented)

### Agent + Security Interaction
11. `tests/test_recommend.py::test_recommend_blocks_invalid_sku_output` (implemented)
12. `tests/test_recommend.py::test_recommend_rollout_not_eligible_rules_only` (implemented)
13. `tests/test_agent_guardrails.py::test_recommend_never_invents_sku` (implemented)
14. `tests/test_agent_guardrails.py::test_support_never_returns_admin_secret` (implemented)
15. `tests/test_decision_logs_fields.py::test_decision_logs_include_retrieved_context_and_policy` (implemented)
16. `tests/test_decision_audits.py::test_reopen_and_extend_and_audit` (implemented)

### Context Rot + CacheRAG Isolation
17. `tests/test_memory_cacherag.py::test_memory_isolation_by_uid` (implemented)
18. `tests/test_memory_cacherag.py::test_session_memory_update_endpoint` (implemented)
19. `tests/test_context_rot.py::test_summary_truncates_over_50_utterances` (implemented)
20. `tests/test_context_rot.py::test_recent_retrieval_expires` (implemented)

### Orders + Storefront + Catalog
21. `tests/test_order_history_paging.py::test_order_history_paging` (implemented)
22. `tests/test_orders_status.py::test_order_status_transitions_valid` (implemented)
23. `tests/test_orders_status.py::test_order_status_transitions_invalid` (implemented)
24. `tests/test_storefront_ui.py::test_storefront_cards_include_specs` (implemented)
25. `tests/test_storefront_ui.py::test_product_detail_shows_features` (implemented)
26. `tests/test_laptop_products_seed.py::test_parse_laptop_products_has_prices` (implemented)
27. `tests/test_laptop_products_seed.py::test_seed_products_from_laptops` (implemented)

### Observability + Admin
28. `tests/test_metrics.py::test_metrics_endpoint` (implemented)
29. `tests/test_security_incident_flow.py::test_security_escalate_and_block_flow` (implemented)
30. `tests/test_admin_overview.py::test_admin_overview_returns_series` (implemented)

## Notes
- Indirect prompt injection test seeds a product spec with hidden instruction.
- Context-rot tests use FakeRedis to simulate TTL + eviction behavior.
