# Pytest Plan (30 Tests)

This plan lists 30 pytest cases covering core flows, security (OWASP LLM Top 10), context-rot, and agent/security interactions.

## Security + Prompt Injection
1. `test_security_detects_unicode_prompt_injection` — unicode obfuscation + jailbreak signal.
2. `test_security_detects_direct_prompt_injection` — plain text prompt injection.
3. `test_security_detects_indirect_prompt_injection_via_catalog` — hidden instruction in product description.
4. `test_security_detects_jailbreak_keyword_patterns` — `ignore previous` etc.
5. `test_security_detects_pii_and_redacts` — PII scrub + OWASP LLM06.
6. `test_security_detects_pci` — credit card string triggers LLM06.
7. `test_security_observer_logs_event_for_recommend` — event saved for recommend endpoint.
8. `test_security_observer_logs_event_for_support` — event saved for support endpoint.
9. `test_security_event_has_owasp_tags` — event analysis includes OWASP tags.
10. `test_security_event_has_mitre_tags` — event analysis includes MITRE tags.

## Agent + Security Interaction
11. `test_recommend_prompt_injection_still_returns_safe_results` — no extra SKUs.
12. `test_support_prompt_injection_returns_safe_response` — no secret leak.
13. `test_recommend_blocks_invalid_sku_output` — guardrail for LLM misbehavior.
14. `test_recommend_rollout_rules_only` — rollout prevents agent use.
15. `test_decision_logs_include_retrieved_context` — decision logs capture context.
16. `test_decision_audits_on_reopen_extend` — audit entries created.

## Context Rot / Memory Isolation
17. `test_memory_isolation_by_uid` — CacheRAG per-UID separation.
18. `test_session_memory_update_endpoint` — summary + retrieval ranks.
19. `test_context_rot_eviction` — old summary replaced after >50 utterances.
20. `test_context_rot_retrieval_ttl` — recent retrieval expires (ttl simulation).

## Orders + Storefront
21. `test_order_history_paging` — limit/offset works.
22. `test_create_order_writes_session_mapping` — order_sessions entry.
23. `test_order_status_transitions_valid` — created→paid→shipped→delivered.
24. `test_order_status_transitions_invalid` — invalid transition rejected.
25. `test_storefront_product_detail_renders_specs` — detail view shows spec list.
26. `test_storefront_featured_cards_show_specs` — cards include GPU/Wi‑Fi/Ports.

## Analytics + Observability
27. `test_metrics_endpoint_available` — `/metrics` returns 200.
28. `test_admin_overview_returns_series` — decision/approval/uptime fields.
29. `test_security_events_pagination` — admin security events paging.
30. `test_incident_flow_escalate_block` — incidents created + blocked flag.

## Notes
- Indirect prompt injection test should use a product spec/description seeded with hidden instruction and verify it is treated as data, not instructions.
- Context rot tests can simulate the Memory class without Redis (FakeRedis).
- Use `RUN_INTEGRATION=1` for full E2E coverage (recommend + order + memory).
