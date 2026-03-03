"""Tests for all new intelligence modules:
- NQE smart questions (gaming, corporate, touch, software)
- NLP search agent (parsing, negation, budget, slot merge)
- Product ranking agent (listwise, diversity, contrastive WHY)
- Episodic memory (episodes, profiles, chat history, summaries)
- Use case advisor (game requirements, software requirements, touch screen)
- CV document forensics (EXIF, double JPEG, receipt, serial)
- GNN fraud detector (heuristic scoring, feature extraction)
"""
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from src.app.deps import DummyRedis


# ===========================================================================
# NQE Smart Questions
# ===========================================================================


class TestLayer1MemoryApis:
    """Validate explicit structured-state and product memory APIs."""

    def test_structured_state_and_product_bank_roundtrip(self):
        from src.app.services.memory import Memory

        mem = Memory(DummyRedis())
        uid = "u-layer1-memory-1"

        mem.set_structured_state(
            uid,
            {
                "budget_max": 1600,
                "last_shortlist_skus": ["SKU-A", "SKU-B"],
                "nqe_answered_fields": {"use_case": "gaming"},
            },
        )
        mem.set_product_memory_bank(
            uid,
            {
                "recent_recommendations": [
                    {"trace_id": "t1", "shortlist_skus": ["SKU-A", "SKU-B"]}
                ]
            },
        )

        structured = mem.get_structured_state(uid)
        product_bank = mem.get_product_memory_bank(uid)
        assert structured.get("budget_max") == 1600
        assert structured.get("last_shortlist_skus") == ["SKU-A", "SKU-B"]
        assert (structured.get("nqe_answered_fields") or {}).get("use_case") == "gaming"
        assert isinstance(product_bank.get("recent_recommendations"), list)
        assert (product_bank.get("recent_recommendations") or [])[0].get("trace_id") == "t1"

    def test_structured_state_survives_regular_kv_writes(self):
        from src.app.services.memory import Memory

        mem = Memory(DummyRedis())
        uid = "u-layer1-memory-2"
        mem.set_structured_state(uid, {"last_shortlist_skus": ["SKU-X"]})
        mem.set_kv(uid, {"unrelated": True})

        structured = mem.get_structured_state(uid)
        kv = mem.get_kv(uid)
        assert structured.get("last_shortlist_skus") == ["SKU-X"]
        assert kv.get("unrelated") is True

class TestNQESmartQuestions:
    """Test the enhanced NQE that asks context-aware questions."""

    def _make_engine(self):
        from src.app.flows.nqe import NextQuestionEngine, NQEInput
        from src.app.rag.retrieve import Retriever

        class FakeTemplates:
            def get_templates(self, *a, **kw):
                return []

        rag = MagicMock(spec=Retriever)
        rag.retrieve.return_value = []
        return NextQuestionEngine(rag, FakeTemplates()), NQEInput

    def test_gaming_query_triggers_gaming_depth_question(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I want a gaming laptop",
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        assert "ask_gaming_depth" in ids

    def test_specific_game_skips_gaming_depth(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I want a laptop for Cyberpunk 2077",
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        # Should NOT ask gaming_depth since specific game was detected
        assert "ask_gaming_depth" not in ids

    def test_corporate_query_triggers_work_type_question(self):
        engine, NQEInput = self._make_engine()
        # Use a query that triggers corporate detection but doesn't auto-resolve subtype
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I need a professional laptop for work",
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        assert "ask_corporate_work_type" in ids

    def test_finance_auto_detected_skips_work_type(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I need a laptop for Excel spreadsheet analysis and Bloomberg terminal",
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        # Finance was auto-detected, should not ask corporate subtype
        assert "ask_corporate_work_type" not in ids

    def test_note_taking_triggers_touch_screen_question(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I want a laptop for note-taking with a stylus",
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        assert "ask_touch_screen_type" in ids

    def test_university_general_shows_subject_options(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            detected_use_case="university_general",
        )
        qs = engine.propose(inp)
        subj_q = [q for q in qs if q.id == "ask_university_subject"]
        assert len(subj_q) == 1
        assert len(subj_q[0].options) >= 6  # CS, Engineering, DS, Design, Architecture, Medical, Law, General

    def test_answered_gaming_depth_not_asked_again(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I want a gaming laptop",
            answered_fields={"gaming_depth": "aaa_heavy"},
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        assert "ask_gaming_depth" not in ids

    def test_software_detection_triggers_confirm(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I need a laptop for AutoCAD and Blender",
            detected_software=["autocad", "blender"],
        )
        qs = engine.propose(inp)
        ids = [q.id for q in qs]
        assert "ask_software_confirm" in ids


# ===========================================================================
# Game / Software Detection
# ===========================================================================

class TestGameSoftwareDetection:

    def test_detect_games_minecraft(self):
        from src.app.flows.nqe import detect_games_in_text
        result = detect_games_in_text("I want to play Minecraft and Fortnite")
        assert "minecraft" in result
        assert "fortnite" in result

    def test_detect_games_space_marines(self):
        from src.app.flows.nqe import detect_games_in_text
        result = detect_games_in_text("I want to play Space Marines 2")
        assert "space_marines_2" in result

    def test_detect_games_cs2(self):
        from src.app.flows.nqe import detect_games_in_text
        assert "cs2" in detect_games_in_text("counter strike 2")
        assert "cs2" in detect_games_in_text("CS2 competitive")

    def test_detect_software_autocad(self):
        from src.app.flows.nqe import detect_software_in_text
        result = detect_software_in_text("I need AutoCAD for my engineering classes")
        assert "autocad" in result

    def test_detect_software_blender_premiere(self):
        from src.app.flows.nqe import detect_software_in_text
        result = detect_software_in_text("I use Blender and Premiere for video editing")
        assert "blender" in result
        assert "adobe_premiere" in result


# ===========================================================================
# NLP Search Agent
# ===========================================================================

class TestNLPSearchAgent:

    def test_parse_budget_under(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I want a laptop under $800")
        assert r.budget_max == 800
        assert r.budget_min is None

    def test_parse_budget_range(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("Looking for something in the $500-$1000 range")
        assert r.budget_min == 500
        assert r.budget_max == 1000

    def test_parse_budget_fuzzy_cheap(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I need a cheap laptop that won't break the bank")
        assert r.budget_max is not None
        assert r.budget_max <= 600

    def test_parse_budget_around(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I'm looking for something around $1000")
        assert r.budget_min == 800  # 1000 * 0.8
        assert r.budget_max == 1200  # 1000 * 1.2

    def test_parse_negation_brand(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I want a laptop but not ASUS and not HP")
        assert "asus" in r.brands_negative
        assert "hp" in r.brands_negative

    def test_parse_negation_general(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("No refurbished laptops please")
        assert "refurbished" in " ".join(r.negations).lower()

    def test_parse_specs_ram(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I need at least 16GB RAM and 512GB SSD")
        assert r.specs.get("ram_gb") == 16
        assert r.specs.get("storage_gb") == 512

    def test_parse_brand_positive(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I prefer Dell or Lenovo laptops")
        assert "dell" in r.brands_positive
        assert "lenovo" in r.brands_positive

    def test_parse_intent_compare(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("Compare Dell XPS 15 vs MacBook Pro")
        assert r.intent == "compare"
        assert r.intent_confidence >= 0.7

    def test_parse_intent_return(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("I want to return my laptop")
        assert r.intent == "return"

    def test_merge_slots_accumulate(self):
        from src.app.services.nlp_search_agent import parse_query, merge_slots
        q1 = parse_query("I want a Dell laptop for gaming")
        q2 = parse_query("under $1500, not refurbished")
        merged = merge_slots(q1, q2)
        assert "dell" in merged.brands_positive
        assert merged.budget_max == 1500
        assert "gaming" in merged.use_case_hints

    def test_merge_slots_negative_overrides_positive(self):
        from src.app.services.nlp_search_agent import parse_query, merge_slots
        q1 = parse_query("I like ASUS laptops")
        q2 = parse_query("actually not ASUS")
        merged = merge_slots(q1, q2)
        assert "asus" in merged.brands_negative
        assert "asus" not in merged.brands_positive

    def test_parse_use_case_hints(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("laptop for university and coding")
        assert "university" in r.use_case_hints
        assert "programming" in r.use_case_hints

    def test_empty_query_returns_defaults(self):
        from src.app.services.nlp_search_agent import parse_query
        r = parse_query("")
        assert r.intent == "recommend"
        assert r.budget_min is None
        assert r.budget_max is None
        assert r.mention_count == 0


# ===========================================================================
# Product Ranking Agent
# ===========================================================================

class TestProductRankingAgent:

    def _make_candidates(self):
        return [
            {"product_id": "A", "brand": "Dell", "ram_gb": 16, "has_dedicated_gpu": True, "gpu_vram_gb": 6, "storage_gb": 512, "price": 999},
            {"product_id": "B", "brand": "Dell", "ram_gb": 16, "has_dedicated_gpu": True, "gpu_vram_gb": 6, "storage_gb": 512, "price": 1050},  # near-identical to A
            {"product_id": "C", "brand": "Dell", "ram_gb": 16, "has_dedicated_gpu": True, "gpu_vram_gb": 6, "storage_gb": 512, "price": 1020},  # near-identical to A
            {"product_id": "D", "brand": "Lenovo", "ram_gb": 32, "has_dedicated_gpu": True, "gpu_vram_gb": 8, "storage_gb": 1024, "price": 1500},
            {"product_id": "E", "brand": "ASUS", "ram_gb": 8, "has_dedicated_gpu": False, "storage_gb": 256, "price": 450},
        ]

    def test_listwise_rerank_returns_top_n(self):
        from src.app.services.product_ranking_agent import listwise_rerank
        results = listwise_rerank(self._make_candidates(), top_n=3)
        assert len(results) == 3
        assert all(r.rank > 0 for r in results)
        assert results[0].rank == 1

    def test_diversity_enforcement(self):
        from src.app.services.product_ranking_agent import listwise_rerank
        # With top_n=3 and max 2 per group, at most 2 Dells should appear
        results = listwise_rerank(self._make_candidates(), max_per_diversity_group=2, top_n=3)
        dell_count = sum(1 for r in results if r.raw.get("brand") == "Dell")
        assert dell_count <= 2

    def test_contrastive_why_generated(self):
        from src.app.services.product_ranking_agent import listwise_rerank
        results = listwise_rerank(self._make_candidates(), top_n=3)
        for r in results:
            assert r.contrastive_why  # should not be empty
            assert len(r.contrastive_why) > 10

    def test_spec_match_scoring(self):
        from src.app.services.product_ranking_agent import listwise_rerank
        req = {"min_ram_gb": 16, "gpu_needed": True, "min_gpu_vram_gb": 6}
        results = listwise_rerank(
            self._make_candidates(),
            required_specs=req,
            top_n=5,
        )
        # Product E (8GB RAM, no GPU) should rank lower than D (32GB, 8GB VRAM)
        rank_d = next(r.rank for r in results if r.product_id == "D")
        rank_e = next(r.rank for r in results if r.product_id == "E")
        assert rank_d < rank_e  # lower rank = better

    def test_budget_fitting(self):
        from src.app.services.product_ranking_agent import listwise_rerank
        results = listwise_rerank(
            self._make_candidates(),
            budget_max=500,
            top_n=3,
        )
        # Product E ($450) should score high on budget fit
        e_result = next((r for r in results if r.product_id == "E"), None)
        assert e_result is not None
        assert e_result.component_scores["budget_fit"] > 0.8

    def test_brand_negative_filter(self):
        from src.app.services.product_ranking_agent import listwise_rerank
        results = listwise_rerank(
            self._make_candidates(),
            brands_negative=["dell"],
            top_n=3,
        )
        # Dells should be scored lower on brand pref
        for r in results:
            if r.raw.get("brand") == "Dell":
                assert r.component_scores["brand_pref"] == 0.0


# ===========================================================================
# Use Case Advisor — Game / Software Requirements
# ===========================================================================

class TestUseCaseAdvisorExtended:

    def test_match_game_requirements_single(self):
        from src.app.services.use_case_advisor import match_game_requirements
        r = match_game_requirements(["cyberpunk_2077"])
        assert r["tier"] == "aaa_heavy"
        assert r["gpu_needed"] is True
        assert r["recommended_ram_gb"] >= 16

    def test_match_game_requirements_aggregates_max(self):
        from src.app.services.use_case_advisor import match_game_requirements
        r = match_game_requirements(["minecraft", "cyberpunk_2077"])
        # Should take the max of minecraft (light) and cyberpunk (aaa_heavy)
        assert r["tier"] == "aaa_heavy"

    def test_match_game_requirements_unknown_game(self):
        from src.app.services.use_case_advisor import match_game_requirements
        r = match_game_requirements(["unknown_game_xyz"])
        assert "unknown_game_xyz" in r["games_not_found"]

    def test_match_software_requirements(self):
        from src.app.services.use_case_advisor import match_software_requirements
        r = match_software_requirements(["autocad", "blender"])
        assert r["gpu_needed"] is True
        assert r["recommended_ram_gb"] >= 16

    def test_match_use_case_new_entries(self):
        from src.app.services.use_case_advisor import match_use_case_from_query
        assert match_use_case_from_query("note taking with stylus") == "note_taking_student"
        assert match_use_case_from_query("AAA gaming ultra settings") == "gaming_aaa_heavy"
        assert match_use_case_from_query("finance and accounting spreadsheets") == "office_finance"
        assert match_use_case_from_query("executive travel laptop") == "office_executive"
        assert match_use_case_from_query("medical student anatomy") == "medical_student"

    def test_assess_touch_screen(self):
        from src.app.services.use_case_advisor import assess_touch_screen_suitability
        r = assess_touch_screen_suitability(
            {"has_touch_screen": True, "has_pen_support": True, "form_factor": "2-in-1"},
            needs_pen=True,
        )
        assert r["suitable"] is True
        r2 = assess_touch_screen_suitability(
            {"has_touch_screen": False},
            needs_pen=True,
        )
        assert r2["suitable"] is False
        assert any("touch" in g.lower() for g in r2["gaps"])

    def test_get_software_specs(self):
        from src.app.services.use_case_advisor import get_software_specs
        s = get_software_specs("autocad")
        assert s is not None
        assert s.get("gpu_needed") is True

    def test_get_game_specs(self):
        from src.app.services.use_case_advisor import get_game_specs
        g = get_game_specs("minecraft")
        assert g is not None
        assert g.get("tier") in ("light", "casual")  # depends on KB version


# ===========================================================================
# Episodic Memory
# ===========================================================================

class TestEpisodicMemory:

    def _make_memory(self):
        """Create a Memory with a fake Redis that stores data in-memory."""
        from src.app.services.memory import Memory
        from src.app.services.episodic_memory import EpisodicMemory, Episode, UserProfile
        store = {}
        redis_mock = MagicMock()
        redis_mock.get.side_effect = lambda k: store.get(k)
        redis_mock.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v)
        redis_mock.expire.return_value = True
        mem = Memory(redis_mock)
        return EpisodicMemory(mem), Episode, UserProfile

    def test_append_and_get_episodes(self):
        ep_mem, Episode, _ = self._make_memory()
        ep = Episode(turn_index=0, query="gaming laptop", response_summary="5 results")
        ep_mem.append_episode("test-uid", ep)
        episodes = ep_mem.get_episodes("test-uid")
        assert len(episodes) == 1
        assert episodes[0]["query"] == "gaming laptop"

    def test_session_context_summary(self):
        ep_mem, Episode, _ = self._make_memory()
        ep_mem.append_episode("u1", Episode(turn_index=0, query="gaming laptop", response_summary="5 results"))
        ep_mem.append_episode("u1", Episode(turn_index=1, query="under $1000", response_summary="3 results",
                                            slots_captured={"budget_max": 1000}))
        summary = ep_mem.get_session_context_summary("u1")
        assert "gaming laptop" in summary
        assert "budget_max=1000" in summary

    def test_user_profile_save_load(self):
        ep_mem, _, UserProfile = self._make_memory()
        profile = UserProfile(
            user_id="user-42",
            preferred_brands=["dell", "lenovo"],
            budget_tier="mid",
        )
        ep_mem.save_user_profile(profile)
        loaded = ep_mem.get_user_profile("user-42")
        assert loaded is not None
        assert "dell" in loaded.preferred_brands
        assert loaded.budget_tier == "mid"

    def test_update_profile_from_session(self):
        ep_mem, _, UserProfile = self._make_memory()
        profile = ep_mem.update_profile_from_session(
            "user-99",
            session_slots={"brands_positive": ["asus"], "budget_max": 500, "use_case_hints": ["gaming"]},
            session_summary="Looked for gaming laptop under $500",
        )
        assert "asus" in profile.preferred_brands
        assert profile.budget_tier == "budget"
        assert "gaming" in profile.typical_use_cases

    def test_save_and_get_chat_history(self):
        ep_mem, Episode, _ = self._make_memory()
        episodes = [
            {"turn_index": 0, "query": "hello", "response_summary": "hi"},
            {"turn_index": 1, "query": "gaming laptop", "response_summary": "5 results"},
        ]
        ep_mem.save_chat_session("user-1", "session-abc", episodes, "Looked for gaming laptop")
        history = ep_mem.get_chat_history("user-1")
        assert len(history) == 1
        assert history[0]["session_id"] == "session-abc"
        assert history[0]["summary"] == "Looked for gaming laptop"

    def test_summarize_session(self):
        ep_mem, Episode, _ = self._make_memory()
        ep_mem.append_episode("s1", Episode(turn_index=0, query="laptop for work", response_summary="10 results"))
        summary = ep_mem.summarize_session("s1")
        assert summary.session_id == "s1"
        assert summary.turn_count >= 1


# ===========================================================================
# CV Document Forensics
# ===========================================================================

class TestCVDocumentForensics:

    def test_serial_format_apple_valid(self):
        from src.app.security.cv_document_forensics import check_serial_format
        r = check_serial_format("C02XG1RRJG5J", "apple")
        assert r.passed is True

    def test_serial_format_apple_invalid(self):
        from src.app.security.cv_document_forensics import check_serial_format
        r = check_serial_format("INVALID!", "apple")
        assert r.passed is False

    def test_serial_format_unknown_brand(self):
        from src.app.security.cv_document_forensics import check_serial_format
        r = check_serial_format("ABC123", "unknown_brand")
        assert r.confidence < 1.0  # low confidence for unknown

    def test_receipt_amount_mismatch(self):
        from src.app.security.cv_document_forensics import check_receipt_authenticity
        r = check_receipt_authenticity(
            extracted_text="Store: TechShop\nTotal: $299.99\nOrder: ABC123",
            claimed_amount=499.99,
        )
        assert r.passed is False
        assert any("amount" in f.lower() for f in r.findings)

    def test_receipt_store_mismatch(self):
        from src.app.security.cv_document_forensics import check_receipt_authenticity
        r = check_receipt_authenticity(
            extracted_text="Store: TechShop\nTotal: $299.99",
            claimed_store="MegaMart",
        )
        assert r.passed is False

    def test_receipt_valid(self):
        from src.app.security.cv_document_forensics import check_receipt_authenticity
        r = check_receipt_authenticity(
            extracted_text="Store: TechShop\nTotal: $299.99",
            claimed_amount=299.99,
            claimed_store="TechShop",
        )
        assert r.passed is True

    def test_double_jpeg_clean(self):
        from src.app.security.cv_document_forensics import check_double_jpeg
        # Create a minimal JPEG with single SOI marker
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
        r = check_double_jpeg(fake_jpeg)
        assert r.passed is True

    def test_double_jpeg_suspect(self):
        from src.app.security.cv_document_forensics import check_double_jpeg
        # Create fake bytes with multiple SOI markers
        fake = b"\xff\xd8\xff\xe0" + b"\x00" * 50 + b"\xff\xd8" + b"\x00" * 50
        r = check_double_jpeg(fake)
        assert r.passed is False
        assert "Multiple JPEG" in "".join(r.findings)

    def test_full_forensic_report_clean(self):
        from src.app.security.cv_document_forensics import run_document_forensics
        # Use a valid minimal image (1x1 pixel PNG)
        import io
        try:
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (10, 10), "white").save(buf, "PNG")
            img_bytes = buf.getvalue()
        except ImportError:
            img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        report = run_document_forensics(img_bytes)
        assert report.image_hash
        assert report.verdict in ("clean", "suspicious", "likely_fraud")

    def test_full_forensic_report_with_serial(self):
        from src.app.security.cv_document_forensics import run_document_forensics
        img_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        report = run_document_forensics(
            img_bytes,
            serial_number="INVALID!",
            claimed_brand="apple",
        )
        serial_checks = [c for c in report.checks if c.check_name == "serial_format"]
        assert len(serial_checks) == 1
        assert serial_checks[0].passed is False


# ===========================================================================
# GNN Fraud Detector
# ===========================================================================

class TestGNNFraudDetector:

    def test_heuristic_low_risk(self):
        from src.app.services.gnn_fraud_detector import _heuristic_fraud_score, SubgraphFeatures
        f = SubgraphFeatures(
            account_id="a1",
            degree=1,
            shared_address_count=0,
            shared_device_count=0,
            account_age_days=365,
        )
        score = _heuristic_fraud_score(f)
        assert score < 0.2

    def test_heuristic_high_risk(self):
        from src.app.services.gnn_fraud_detector import _heuristic_fraud_score, SubgraphFeatures
        f = SubgraphFeatures(
            account_id="a2",
            degree=15,
            shared_address_count=5,
            shared_device_count=4,
            shared_ip_count=6,
            max_ring_size=12,
            transaction_velocity_24h=8,
            account_age_days=2,
            chargeback_rate=0.3,
        )
        score = _heuristic_fraud_score(f)
        assert score >= 0.7

    def test_feature_vector_length(self):
        from src.app.services.gnn_fraud_detector import SubgraphFeatures, FEATURE_DIM
        f = SubgraphFeatures(account_id="x")
        vec = f.to_vector()
        assert len(vec) == FEATURE_DIM

    def test_predict_fraud_risk_fallback(self):
        from src.app.services.gnn_fraud_detector import predict_fraud_risk
        # Without Neo4j running, should fall back to heuristic with zero features
        result = predict_fraud_risk("test-account-123")
        assert result.method == "heuristic"
        assert 0.0 <= result.gnn_score <= 1.0
        assert result.account_id == "test-account-123"

    def test_gnn_result_explanation(self):
        from src.app.services.gnn_fraud_detector import predict_fraud_risk
        result = predict_fraud_risk("clean-account")
        assert result.explanation  # should have some text
        assert "No significant risk factors" in result.explanation or "Risk factors:" in result.explanation
