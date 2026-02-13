# ShopSquire Product-Agnostic Platform Roadmap

> **Generated**: February 2026
> **Purpose**: Prioritized MVP roadmap - Rules → ML → Models with test coverage
> **Approach**: Cost-pragmatic, vertical-agnostic, evidence-first pipeline

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Phase 0: Core Foundation (Rules-First)](#2-phase-0-core-foundation-rules-first)
3. [Phase 1: Enhanced Rules & Policy Layer](#3-phase-1-enhanced-rules--policy-layer)
4. [Phase 2: Small ML & Signal Fusion](#4-phase-2-small-ml--signal-fusion)
5. [Phase 3: CV/OCR Pipeline (YOLO ROI Detection)](#5-phase-3-cvocr-pipeline-yolo-roi-detection)
6. [Phase 4: Advanced Models & Fraud Detection](#6-phase-4-advanced-models--fraud-detection)
7. [Phase 5: Inventory & ERP Integration](#7-phase-5-inventory--erp-integration)
8. [Phase 6: Evaluation & Monitoring](#8-phase-6-evaluation--monitoring)
9. [Vertical Pack System](#9-vertical-pack-system)
10. [Complete File Manifest](#10-complete-file-manifest)
11. [Test Coverage Matrix](#11-test-coverage-matrix)
12. [Quick Reference: Phase Checklist](#12-quick-reference-phase-checklist)

---

## 1. Architecture Overview

### Target Architecture: Tiered Execution Pattern

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INCOMING REQUEST                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  T0: RULES/HEURISTICS (Cheap, Fast, High Precision)                 │
│  ├─ Image quality validation (blur, size, format)                   │
│  ├─ Perceptual hash check (reuse detection)                         │
│  ├─ Policy eligibility (return window, SKU blacklist)               │
│  ├─ Required views check (front/back/serial per vertical)           │
│  └─ Quick OCR attempt (barcode/QR decode)                           │
│  GATE: If confidence ≥ 0.95 → DECISION                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │ Low confidence / triggers
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  T1: SMALL ML (Fast inference, ROI detection)                       │
│  ├─ YOLO ROI detection (product, serial_plate, label, barcode)      │
│  ├─ Lightweight OCR on cropped regions                              │
│  ├─ Basic damage classifier (binary: damaged/intact)                │
│  ├─ Signal fusion scorer (GBDT/logistic)                            │
│  └─ Inventory lookup + order history (parallel)                     │
│  GATE: If confidence ≥ 0.85 → DECISION                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │ Low confidence / high risk / fraud
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  T2: HEAVY ML/LLM (Expensive, High Accuracy)                        │
│  ├─ Enhanced CV pipeline (forensics, segmentation)                  │
│  ├─ LLM reasoning for ambiguous cases                               │
│  ├─ Visual embedding similarity (CLIP-like)                         │
│  ├─ Multi-signal correlation                                        │
│  └─ Fraud detection ensemble                                        │
│  GATE: If confidence ≥ 0.80 → DECISION                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │ Still uncertain / policy requires
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  T3: HUMAN REVIEW                                                   │
│  ├─ Queue with full context                                         │
│  ├─ Active learning: feed back to model training                    │
│  └─ Audit trail for compliance                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Canonical Schemas (Multi-Tenant)

| Schema | Purpose | Status |
|--------|---------|--------|
| `Product` | SKU, category, attributes, specs | ✅ Exists |
| `Order` | Order history, line items | ✅ Exists |
| `ReturnCase` | Return request with evidence | ✅ Exists |
| `EvidenceBundle` | Images, OCR artifacts, hashes | ✅ Exists |
| `DecisionTrace` | Full audit trail | ✅ Exists (partial) |
| `SecurityEvent` | Threat signals | ✅ Exists |
| `HumanReviewTask` | Escalation queue | ✅ Exists |

---

## 2. Phase 0: Core Foundation (Rules-First)

> **Goal**: Gate expensive model calls with cheap, high-precision rules
> **Duration**: Week 1-2
> **Cost Impact**: Prevents 60-80% of unnecessary ML invocations

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/schemas/return_case.py` | ReturnCase Pydantic schema |
| `src/app/schemas/evidence_bundle.py` | EvidenceBundle schema with hashes |
| `src/app/schemas/human_review.py` | HumanReviewTask schema |
| `src/app/models/orm.py` | SQLAlchemy ORM: ReturnCase, EvidenceBundle, HumanReviewTask |
| `src/app/rules/image_quality.py` | Image quality gate rules |
| `src/app/rules/eligibility.py` | Return eligibility rules |
| `src/app/rules/required_views.py` | Required image views per vertical |
| `src/app/rules/hash_reuse.py` | Perceptual hash reuse detection |
| `src/app/rules/barcode_decode.py` | Fast barcode/QR decode |
| `src/app/rules/tier0_gate.py` | Tier 0 decision gate |
| `db/migrations/0002_add_evidence_bundles.sql` | Evidence bundle table (legacy) |
| `db/migrations/V20260206_add_evidence_and_human_review.sql` | Evidence + human review migration |
| `config/rules/image_quality_thresholds.json` | Quality thresholds config |
| `config/rules/eligibility_policies.json` | Eligibility rules config |
| `config/verticals/electronics.json` | Electronics vertical pack |
| `config/verticals/fashion.json` | Fashion vertical pack |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/models/orm.py` | Import new ORM models |
| `src/app/models/schemas.py` | Import new Pydantic schemas |
| `src/app/services/cv_tiered.py` | Add Tier 0 rules gate before ML |
| `src/app/services/policy_evaluator.py` | Add eligibility rule evaluation |
| `db/schema.sql` | Add new table definitions |
| `config/feature_flags.json` | Add `TIER0_RULES_ENABLED` flag |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/services/cv_triage_basic.py` | Extract quality checks to rules module |
| `src/app/services/image_forensics.py` | Add hash computation for reuse detection |

### Tests After Phase 0

**pytest:**
```bash
# Run after Phase 0 completion
pytest tests/rules/ -v --tb=short
pytest tests/models/test_return_case.py -v
pytest tests/models/test_evidence_bundle.py -v
pytest tests/api/test_returns_eligibility.py -v
pytest tests/cv/test_image_quality_rules.py -v
```

**Playwright:**
```bash
# Smoke test: returns flow with quality gate
npx playwright test tests/playwright/returns_quality_gate.spec.ts
```

**Test Files to CREATE:**
- `tests/rules/test_image_quality.py`
- `tests/rules/test_eligibility.py`
- `tests/rules/test_required_views.py`
- `tests/rules/test_hash_reuse.py`
- `tests/rules/test_barcode_decode.py`
- `tests/rules/test_tier0_gate.py`
- `tests/models/test_return_case.py`
- `tests/models/test_evidence_bundle.py`
- `tests/playwright/returns_quality_gate.spec.ts`

---

## 3. Phase 1: Enhanced Rules & Policy Layer

> **Goal**: Comprehensive rule engine with vertical-specific policies
> **Duration**: Week 2-3
> **Pattern**: Deterministic constraints before AI signals

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/rules/engine.py` | Central rule engine with priority ordering |
| `src/app/rules/sku_blacklist.py` | SKU/category blacklist rules |
| `src/app/rules/return_window.py` | Time-based eligibility rules |
| `src/app/rules/serial_patterns.py` | Brand-specific serial validation (regex) |
| `src/app/rules/threshold_gates.py` | Dynamic threshold gates |
| `src/app/rules/fraud_heuristics.py` | Rule-based fraud signals |
| `src/app/rules/escalation_triggers.py` | When to escalate to higher tiers |
| `src/app/policy/vertical_pack.py` | Vertical pack loader/registry |
| `src/app/policy/taxonomy.py` | Category/damage type taxonomies |
| `src/app/policy/thresholds.py` | Per-vertical threshold management |
| `src/app/routers/rules_admin.py` | Admin API for rule management |
| `config/rules/serial_patterns.json` | Serial regex by brand family |
| `config/rules/fraud_heuristics.json` | Fraud rule definitions |
| `config/rules/escalation_triggers.json` | Escalation trigger config |
| `config/verticals/home_garden.json` | Home & Garden vertical pack |
| `config/verticals/sports.json` | Sports/Outdoors vertical pack |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/services/orchestrator.py` | Integrate rule engine before ML |
| `src/app/services/tier_router.py` | Use rule confidence for routing |
| `src/app/services/policy_evaluator.py` | Add vertical-aware evaluation |
| `src/app/routers/admin.py` | Add rules management endpoints |
| `src/app/main.py` | Mount rules_admin router |
| `config/feature_flags.json` | Add `VERTICAL_PACKS_ENABLED` flag |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/services/expanded_rules.py` | Migrate to new rule engine format |
| `src/app/services/rule_store.py` | Add vertical-scoped rule storage |

### Tests After Phase 1

**pytest:**
```bash
pytest tests/rules/ -v --tb=short
pytest tests/policy/test_vertical_pack.py -v
pytest tests/policy/test_taxonomy.py -v
pytest tests/api/test_rules_admin.py -v
pytest tests/integration/test_rule_engine.py -v
```

**Playwright:**
```bash
npx playwright test tests/playwright/admin_rules_management.spec.ts
npx playwright test tests/playwright/vertical_switching.spec.ts
```

**Test Files to CREATE:**
- `tests/rules/test_engine.py`
- `tests/rules/test_sku_blacklist.py`
- `tests/rules/test_serial_patterns.py`
- `tests/rules/test_fraud_heuristics.py`
- `tests/rules/test_escalation_triggers.py`
- `tests/policy/test_vertical_pack.py`
- `tests/policy/test_taxonomy.py`
- `tests/policy/test_thresholds.py`
- `tests/api/test_rules_admin.py`
- `tests/integration/test_rule_engine.py`
- `tests/playwright/admin_rules_management.spec.ts`
- `tests/playwright/vertical_switching.spec.ts`

---

## 4. Phase 2: Small ML & Signal Fusion

> **Goal**: Lightweight models for signal extraction, GBDT scorer for fusion
> **Duration**: Week 3-4
> **Pattern**: Rules → Small ML → Escalate when confidence low

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/ml/signal_fusion.py` | GBDT/logistic signal fusion scorer |
| `src/app/ml/feature_extractor.py` | Structured feature extraction |
| `src/app/ml/calibration.py` | Confidence calibration layer |
| `src/app/ml/training/fusion_trainer.py` | Signal fusion model trainer |
| `src/app/ml/training/active_learning.py` | Active learning loop |
| `src/app/services/parallel_executor.py` | Fan-out/fan-in orchestrator |
| `src/app/services/signal_collector.py` | Collect signals from multiple sources |
| `src/app/services/cache_manager.py` | Aggressive caching for embeddings/hashes |
| `src/app/schemas/ml_signals.py` | Signal schemas (CV, OCR, fraud, inventory) |
| `models/signal_fusion.pkl` | Trained fusion model |
| `models/calibrator.pkl` | Calibration model |
| `config/ml/fusion_features.json` | Feature definitions |
| `config/ml/calibration_params.json` | Calibration parameters |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/services/orchestrator.py` | Add signal fusion step |
| `src/app/services/cv_tiered.py` | Output structured signals |
| `src/app/services/tier_router.py` | Use fusion score for routing |
| `src/app/services/fraud_scorer.py` | Output signals for fusion |
| `src/app/analytics/risk_scoring.py` | Integrate with fusion |
| `src/app/observability/metrics.py` | Add fusion metrics |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/services/parallel_agent_executor.py` | Extract to generic parallel executor |
| `src/app/services/confidence_calibration.py` | Migrate to ml/calibration.py |

### Tests After Phase 2

**pytest:**
```bash
pytest tests/ml/test_signal_fusion.py -v
pytest tests/ml/test_feature_extractor.py -v
pytest tests/ml/test_calibration.py -v
pytest tests/services/test_parallel_executor.py -v
pytest tests/services/test_signal_collector.py -v
pytest tests/integration/test_tiered_routing.py -v
```

**Playwright:**
```bash
npx playwright test tests/playwright/decision_confidence.spec.ts
```

**Test Files to CREATE:**
- `tests/ml/test_signal_fusion.py`
- `tests/ml/test_feature_extractor.py`
- `tests/ml/test_calibration.py`
- `tests/ml/test_active_learning.py`
- `tests/services/test_parallel_executor.py`
- `tests/services/test_signal_collector.py`
- `tests/services/test_cache_manager.py`
- `tests/integration/test_tiered_routing.py`
- `tests/playwright/decision_confidence.spec.ts`

---

## 5. Phase 3: CV/OCR Pipeline (YOLO ROI Detection)

> **Goal**: Shared ROI detector + OCR pipeline, product-agnostic
> **Duration**: Week 4-6
> **Pattern**: YOLO for detection, separate OCR for recognition

### ROI Classes to Train (Vertical-Agnostic)

| Class | Description | Use Case |
|-------|-------------|----------|
| `product` | Main product body | All verticals |
| `packaging_box` | Shipping/product box | Condition check |
| `shipping_label` | Address/tracking label | Verification |
| `barcode` | UPC/EAN barcode | SKU validation |
| `qr_code` | QR codes | Quick decode |
| `serial_plate` | Serial number area | Electronics |
| `screen` | Display/screen area | Electronics damage |
| `hinge` | Hinge areas (laptops) | Damage detection |
| `seal_tamper` | Security seals | Fraud detection |
| `receipt_document` | Receipts, invoices | OCR extraction |
| `brand_logo` | Logo placement | Category match |
| `tag_label` | Price/product tags | Fashion |

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/cv/roi_detector.py` | YOLO-based ROI detector |
| `src/app/cv/ocr_pipeline.py` | Detection + Recognition + Post-processing |
| `src/app/cv/ocr_postprocess.py` | Regex, normalization, vendor dictionaries |
| `src/app/cv/barcode_decoder.py` | Barcode/QR decode with fallbacks |
| `src/app/cv/image_normalizer.py` | Input normalization (resize, enhance) |
| `src/app/cv/roi_cropper.py` | Crop ROIs for downstream models |
| `src/app/cv/evidence_writer.py` | Write structured artifacts |
| `src/app/cv/model_registry.py` | Model version registry |
| `src/app/cv/warmup.py` | Model warming on startup |
| `src/app/schemas/cv_artifacts.py` | CV artifact schemas |
| `src/app/routers/cv_evidence.py` | Evidence bundle API |
| `models/yolo_roi_v1.pt` | Trained YOLO ROI model |
| `config/cv/roi_classes.json` | ROI class definitions |
| `config/cv/ocr_patterns.json` | OCR post-processing patterns |
| `config/cv/vendor_dictionaries.json` | Vendor-specific corrections |
| `data/training/roi_annotations/` | Training data directory |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/services/cv_tiered.py` | Use new ROI detector |
| `src/app/services/cv_ocr.py` | Integrate new OCR pipeline |
| `src/app/services/cv_tier2_pipeline.py` | Use ROI cropping |
| `src/app/services/cv_damage_classifier.py` | Classify on cropped ROIs |
| `src/app/services/order_serials.py` | Use OCR pipeline for extraction |
| `src/app/routers/cv.py` | Add evidence endpoints |
| `src/app/main.py` | Mount cv_evidence router |
| `config/feature_flags.json` | Add `YOLO_ROI_ENABLED` flag |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/services/cv_object_detector.py` | Merge into roi_detector.py |
| `src/app/services/cv_provider.py` | Simplify to provider abstraction only |
| `src/app/services/image_intake.py` | Use new normalizer |

### Tests After Phase 3

**pytest:**
```bash
pytest tests/cv/test_roi_detector.py -v
pytest tests/cv/test_ocr_pipeline.py -v
pytest tests/cv/test_barcode_decoder.py -v
pytest tests/cv/test_image_normalizer.py -v
pytest tests/cv/test_evidence_writer.py -v
pytest tests/api/test_cv_evidence.py -v
pytest tests/integration/test_cv_full_pipeline.py -v
```

**Playwright:**
```bash
npx playwright test tests/playwright/returns_image_upload.spec.ts
npx playwright test tests/playwright/cv_evidence_display.spec.ts
```

**Test Files to CREATE:**
- `tests/cv/test_roi_detector.py`
- `tests/cv/test_ocr_pipeline.py`
- `tests/cv/test_ocr_postprocess.py`
- `tests/cv/test_barcode_decoder.py`
- `tests/cv/test_image_normalizer.py`
- `tests/cv/test_roi_cropper.py`
- `tests/cv/test_evidence_writer.py`
- `tests/cv/test_model_registry.py`
- `tests/api/test_cv_evidence.py`
- `tests/integration/test_cv_full_pipeline.py`
- `tests/playwright/returns_image_upload.spec.ts`
- `tests/playwright/cv_evidence_display.spec.ts`

---

## 6. Phase 4: Advanced Models & Fraud Detection

> **Goal**: Damage segmentation, visual similarity, fraud ensemble
> **Duration**: Week 6-8
> **Pattern**: Two-stage (ROI → specialized model), layered fraud

### Damage Detection Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: ROI Detection (YOLO)                                      │
│  Find: screen, hinge, corner, body, seal                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: Damage Classification on Cropped ROIs                     │
│  ├─ Binary: damaged / intact                                        │
│  ├─ Multi-class: screen_crack, body_dent, hinge_damage, scratch     │
│  └─ Severity: minor, moderate, severe                               │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3: Segmentation (Optional, for severe cases)                 │
│  Mask R-CNN / YOLO-seg for precise damage boundaries                │
└─────────────────────────────────────────────────────────────────────┘
```

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/cv/damage_classifier.py` | Multi-class damage classifier |
| `src/app/cv/damage_segmenter.py` | Optional segmentation model |
| `src/app/cv/visual_embedder.py` | CLIP-like visual embeddings |
| `src/app/cv/catalog_matcher.py` | Match against catalog images |
| `src/app/cv/category_detector.py` | Detect product category from image |
| `src/app/fraud/reuse_detector.py` | Perceptual hash + known fraud DB |
| `src/app/fraud/manipulation_detector.py` | ELA, splice, copy-move |
| `src/app/fraud/inconsistency_checker.py` | Cross-signal inconsistencies |
| `src/app/fraud/behavioral_scorer.py` | Account age, return frequency |
| `src/app/fraud/ensemble.py` | Fraud signal ensemble |
| `src/app/schemas/fraud_signals.py` | Fraud signal schemas |
| `src/app/routers/fraud_analysis.py` | Fraud analysis API |
| `models/damage_classifier_v1.pkl` | Damage classifier model |
| `models/visual_embedder.pkl` | Visual embedding model |
| `config/fraud/known_hashes.db` | Known fraud hash database |
| `config/fraud/behavioral_thresholds.json` | Behavioral thresholds |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/services/cv_tier2_pipeline.py` | Use new damage models |
| `src/app/services/image_forensics.py` | Integrate manipulation detector |
| `src/app/services/fraud_scorer.py` | Use fraud ensemble |
| `src/app/services/reverse_image_search.py` | Use visual embedder |
| `src/app/ml/signal_fusion.py` | Add fraud signals |
| `src/app/routers/fraud.py` | Add analysis endpoints |
| `config/feature_flags.json` | Add `FRAUD_ENSEMBLE_ENABLED` flag |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/services/cv_damage_classifier.py` | Migrate to cv/damage_classifier.py |
| `src/app/services/image_forensics.py` | Split into fraud/ modules |

### Tests After Phase 4

**pytest:**
```bash
pytest tests/cv/test_damage_classifier.py -v
pytest tests/cv/test_visual_embedder.py -v
pytest tests/cv/test_catalog_matcher.py -v
pytest tests/fraud/test_reuse_detector.py -v
pytest tests/fraud/test_manipulation_detector.py -v
pytest tests/fraud/test_inconsistency_checker.py -v
pytest tests/fraud/test_behavioral_scorer.py -v
pytest tests/fraud/test_ensemble.py -v
pytest tests/api/test_fraud_analysis.py -v
pytest tests/integration/test_fraud_detection.py -v
```

**Playwright:**
```bash
npx playwright test tests/playwright/fraud_detection_ui.spec.ts
npx playwright test tests/playwright/damage_classification_display.spec.ts
```

**Test Files to CREATE:**
- `tests/cv/test_damage_classifier.py`
- `tests/cv/test_damage_segmenter.py`
- `tests/cv/test_visual_embedder.py`
- `tests/cv/test_catalog_matcher.py`
- `tests/cv/test_category_detector.py`
- `tests/fraud/test_reuse_detector.py`
- `tests/fraud/test_manipulation_detector.py`
- `tests/fraud/test_inconsistency_checker.py`
- `tests/fraud/test_behavioral_scorer.py`
- `tests/fraud/test_ensemble.py`
- `tests/api/test_fraud_analysis.py`
- `tests/integration/test_fraud_detection.py`
- `tests/playwright/fraud_detection_ui.spec.ts`
- `tests/playwright/damage_classification_display.spec.ts`

---

## 7. Phase 5: Inventory & ERP Integration

> **Goal**: Real inventory sync, ERP/EDI integration, warehouse verification
> **Duration**: Week 8-10
> **Pattern**: Webhook-driven sync, parallel lookups

### Integration Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    INVENTORY INTEGRATION LAYER                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Shopify    │    │   BigComm    │    │    Custom    │          │
│  │   Adapter    │    │   Adapter    │    │    Adapter   │          │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘          │
│         │                   │                   │                   │
│         └───────────────────┼───────────────────┘                   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              CANONICAL INVENTORY MODEL                       │   │
│  │  sku, warehouse_id, available, reserved, reorder_point      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                             │                                       │
│         ┌───────────────────┼───────────────────┐                   │
│         ▼                   ▼                   ▼                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Returns    │    │   Reorder    │    │   Demand     │          │
│  │   Validator  │    │   Agent      │    │   Forecast   │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      ERP/EDI INTEGRATION                            │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   SAP/EDI    │    │   NetSuite   │    │   Custom ERP │          │
│  │   Connector  │    │   Connector  │    │   Connector  │          │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘          │
│         │                   │                   │                   │
│         └───────────────────┼───────────────────┘                   │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   EDI MESSAGE HANDLER                        │   │
│  │  850 (PO), 856 (ASN), 810 (Invoice), 997 (ACK)              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                             │                                       │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   INVENTORY SYNC                             │   │
│  │  Bi-directional sync with conflict resolution               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/inventory/canonical_model.py` | Unified inventory model |
| `src/app/inventory/sync_engine.py` | Inventory sync orchestrator |
| `src/app/inventory/adapters/shopify.py` | Shopify inventory adapter |
| `src/app/inventory/adapters/bigcommerce.py` | BigCommerce adapter |
| `src/app/inventory/adapters/custom.py` | Custom API adapter |
| `src/app/inventory/adapters/base.py` | Base adapter interface |
| `src/app/inventory/returns_validator.py` | Validate returns against inventory |
| `src/app/inventory/reorder_agent.py` | Automated reorder recommendations |
| `src/app/erp/edi_handler.py` | EDI message handler |
| `src/app/erp/connectors/sap.py` | SAP EDI connector |
| `src/app/erp/connectors/netsuite.py` | NetSuite connector |
| `src/app/erp/connectors/base.py` | Base connector interface |
| `src/app/erp/message_parser.py` | EDI message parsing |
| `src/app/erp/conflict_resolver.py` | Sync conflict resolution |
| `src/app/schemas/inventory_sync.py` | Sync event schemas |
| `src/app/schemas/edi_messages.py` | EDI message schemas |
| `src/app/routers/inventory_sync.py` | Inventory sync API |
| `src/app/routers/erp_webhooks.py` | ERP webhook handlers |
| `connectors/shopify/inventory.py` | Shopify inventory connector |
| `connectors/bigcommerce/inventory.py` | BigCommerce connector |
| `config/erp/edi_mappings.json` | EDI field mappings |
| `config/erp/sync_policies.json` | Sync timing/conflict policies |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/services/inventory_agent.py` | Use canonical model |
| `src/app/services/inventory_rules.py` | Integrate sync events |
| `src/app/services/warehouse_verification.py` | Use real stock data |
| `src/app/services/demand_forecast.py` | Use sync history |
| `src/app/services/erp_edi.py` | Implement real EDI |
| `src/app/routers/inventory.py` | Add sync endpoints |
| `connectors/shopify/client.py` | Add inventory methods |
| `config/feature_flags.json` | Add `ERP_INTEGRATION_ENABLED` flag |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/services/erp_edi.py` | Migrate to erp/ module structure |
| `connectors/shopify/` | Add inventory support |

### Tests After Phase 5

**pytest:**
```bash
pytest tests/inventory/test_canonical_model.py -v
pytest tests/inventory/test_sync_engine.py -v
pytest tests/inventory/test_adapters.py -v
pytest tests/inventory/test_returns_validator.py -v
pytest tests/erp/test_edi_handler.py -v
pytest tests/erp/test_connectors.py -v
pytest tests/erp/test_conflict_resolver.py -v
pytest tests/api/test_inventory_sync.py -v
pytest tests/api/test_erp_webhooks.py -v
pytest tests/integration/test_inventory_e2e.py -v
```

**Playwright:**
```bash
npx playwright test tests/playwright/inventory_dashboard.spec.ts
npx playwright test tests/playwright/reorder_alerts.spec.ts
```

**Test Files to CREATE:**
- `tests/inventory/test_canonical_model.py`
- `tests/inventory/test_sync_engine.py`
- `tests/inventory/test_adapters.py`
- `tests/inventory/test_returns_validator.py`
- `tests/inventory/test_reorder_agent.py`
- `tests/erp/test_edi_handler.py`
- `tests/erp/test_connectors.py`
- `tests/erp/test_message_parser.py`
- `tests/erp/test_conflict_resolver.py`
- `tests/api/test_inventory_sync.py`
- `tests/api/test_erp_webhooks.py`
- `tests/integration/test_inventory_e2e.py`
- `tests/playwright/inventory_dashboard.spec.ts`
- `tests/playwright/reorder_alerts.spec.ts`

---

## 8. Phase 6: Evaluation & Monitoring

> **Goal**: Offline eval sets, online drift, cost/latency dashboards
> **Duration**: Week 10-12
> **Pattern**: Replayable traces, guardrails, active learning feedback

### Files to CREATE

| File | Purpose |
|------|---------|
| `src/app/eval/offline_runner.py` | Offline evaluation runner |
| `src/app/eval/eval_sets/` | Evaluation datasets per vertical |
| `src/app/eval/metrics.py` | Eval metrics (precision, recall, F1) |
| `src/app/eval/replay.py` | Decision trace replay |
| `src/app/eval/ab_test.py` | A/B test framework |
| `src/app/monitoring/drift_detector.py` | Model drift detection |
| `src/app/monitoring/cost_tracker.py` | Per-decision cost tracking |
| `src/app/monitoring/latency_tracker.py` | P50/P95/P99 latency |
| `src/app/monitoring/guardrails.py` | Runtime guardrails |
| `src/app/monitoring/alerts.py` | Alert definitions |
| `src/app/monitoring/dashboards/cost.json` | Cost dashboard config |
| `src/app/monitoring/dashboards/accuracy.json` | Accuracy dashboard config |
| `src/app/training/feedback_loop.py` | Human review → training data |
| `src/app/training/data_exporter.py` | Export training data |
| `src/app/routers/eval.py` | Evaluation API |
| `src/app/routers/monitoring.py` | Monitoring API |
| `config/eval/thresholds.json` | Eval pass/fail thresholds |
| `config/monitoring/alerts.json` | Alert definitions |

### Files to EDIT

| File | Changes |
|------|---------|
| `src/app/observability/metrics.py` | Add eval/cost metrics |
| `src/app/observability/drift.py` | Integrate drift detector |
| `src/app/services/decision_log.py` | Add replay capability |
| `src/app/services/trace_broker.py` | Feed training loop |
| `src/app/main.py` | Mount eval/monitoring routers |
| `config/observability/grafana_dashboard.json` | Add eval panels |
| `config/observability/prometheus_rules.yml` | Add alert rules |

### Files to REFACTOR

| File | Refactoring |
|------|-------------|
| `src/app/eval/runner.py` | Expand to offline_runner.py |
| `src/app/analytics/ragas.py` | Integrate with eval framework |

### Tests After Phase 6

**pytest:**
```bash
pytest tests/eval/test_offline_runner.py -v
pytest tests/eval/test_metrics.py -v
pytest tests/eval/test_replay.py -v
pytest tests/eval/test_ab_test.py -v
pytest tests/monitoring/test_drift_detector.py -v
pytest tests/monitoring/test_cost_tracker.py -v
pytest tests/monitoring/test_guardrails.py -v
pytest tests/training/test_feedback_loop.py -v
pytest tests/api/test_eval_api.py -v
pytest tests/api/test_monitoring_api.py -v
```

**Playwright:**
```bash
npx playwright test tests/playwright/eval_dashboard.spec.ts
npx playwright test tests/playwright/cost_dashboard.spec.ts
```

**Test Files to CREATE:**
- `tests/eval/test_offline_runner.py`
- `tests/eval/test_metrics.py`
- `tests/eval/test_replay.py`
- `tests/eval/test_ab_test.py`
- `tests/monitoring/test_drift_detector.py`
- `tests/monitoring/test_cost_tracker.py`
- `tests/monitoring/test_latency_tracker.py`
- `tests/monitoring/test_guardrails.py`
- `tests/monitoring/test_alerts.py`
- `tests/training/test_feedback_loop.py`
- `tests/training/test_data_exporter.py`
- `tests/api/test_eval_api.py`
- `tests/api/test_monitoring_api.py`
- `tests/playwright/eval_dashboard.spec.ts`
- `tests/playwright/cost_dashboard.spec.ts`

---

## 9. Vertical Pack System

### Vertical Pack Contract

Each vertical pack defines:

```json
{
  "vertical_id": "electronics",
  "display_name": "Electronics & Devices",
  "version": "1.0.0",

  "taxonomy": {
    "categories": ["smartphone", "laptop", "tablet", "wearable", "accessory"],
    "damage_types": ["screen_crack", "body_dent", "hinge_damage", "water_damage", "battery_swell"],
    "fraud_reasons": ["serial_mismatch", "imei_blacklist", "reuse_detection", "manipulation"]
  },

  "required_evidence": {
    "views": ["front", "back", "serial_plate"],
    "optional_views": ["screen_on", "packaging"],
    "min_images": 3,
    "max_images": 10
  },

  "thresholds": {
    "tier_escalation": {
      "t0_to_t1_confidence": 0.95,
      "t1_to_t2_confidence": 0.85,
      "t2_to_human_confidence": 0.80
    },
    "auto_approve_max_value": 250.00,
    "fraud_alert_threshold": 0.70
  },

  "rules": {
    "eligibility": {
      "return_window_days": 30,
      "excluded_categories": ["final_sale"],
      "require_original_packaging": false
    },
    "serial_patterns": {
      "apple": "^[A-Z0-9]{12}$",
      "samsung": "^R[A-Z0-9]{10}$"
    }
  },

  "models": {
    "roi_detector": "yolo_roi_v1",
    "damage_classifier": "damage_electronics_v1",
    "ocr_model": "paddleocr_v3"
  },

  "sku_metadata_mapping": {
    "brand_field": "vendor",
    "category_field": "product_type",
    "serial_field": "variant_sku"
  }
}
```

### Vertical Packs to Create

| Vertical | File | Priority |
|----------|------|----------|
| Electronics | `config/verticals/electronics.json` | P0 |
| Fashion | `config/verticals/fashion.json` | P1 |
| Home & Garden | `config/verticals/home_garden.json` | P2 |
| Sports/Outdoors | `config/verticals/sports.json` | P2 |
| Luxury | `config/verticals/luxury.json` | P3 |

---

## 10. Complete File Manifest

### Phase 0 Files (22 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/schemas/return_case.py` | P0 |
| CREATE | `src/app/schemas/evidence_bundle.py` | P0 |
| CREATE | `src/app/schemas/human_review.py` | P0 |
| CREATE | `src/app/models/return_case.py` | P0 |
| CREATE | `src/app/models/evidence_bundle.py` | P0 |
| CREATE | `src/app/models/human_review_task.py` | P0 |
| CREATE | `src/app/rules/image_quality.py` | P0 |
| CREATE | `src/app/rules/eligibility.py` | P0 |
| CREATE | `src/app/rules/required_views.py` | P0 |
| CREATE | `src/app/rules/hash_reuse.py` | P0 |
| CREATE | `src/app/rules/barcode_decode.py` | P0 |
| CREATE | `src/app/rules/tier0_gate.py` | P0 |
| CREATE | `db/migrations/V20260206_return_case.sql` | P0 |
| CREATE | `db/migrations/V20260206_evidence_bundle.sql` | P0 |
| CREATE | `db/migrations/V20260206_human_review.sql` | P0 |
| CREATE | `config/rules/image_quality_thresholds.json` | P0 |
| CREATE | `config/rules/eligibility_policies.json` | P0 |
| CREATE | `config/verticals/electronics.json` | P0 |
| CREATE | `config/verticals/fashion.json` | P1 |
| EDIT | `src/app/models/orm.py` | P0 |
| EDIT | `src/app/services/cv_tiered.py` | P0 |
| REFACTOR | `src/app/services/cv_triage_basic.py` | P0 |

### Phase 1 Files (20 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/rules/engine.py` | P0 |
| CREATE | `src/app/rules/sku_blacklist.py` | P0 |
| CREATE | `src/app/rules/return_window.py` | P0 |
| CREATE | `src/app/rules/serial_patterns.py` | P0 |
| CREATE | `src/app/rules/threshold_gates.py` | P0 |
| CREATE | `src/app/rules/fraud_heuristics.py` | P0 |
| CREATE | `src/app/rules/escalation_triggers.py` | P0 |
| CREATE | `src/app/policy/vertical_pack.py` | P0 |
| CREATE | `src/app/policy/taxonomy.py` | P0 |
| CREATE | `src/app/policy/thresholds.py` | P0 |
| CREATE | `src/app/routers/rules_admin.py` | P1 |
| CREATE | `config/rules/serial_patterns.json` | P0 |
| CREATE | `config/rules/fraud_heuristics.json` | P0 |
| CREATE | `config/rules/escalation_triggers.json` | P0 |
| CREATE | `config/verticals/home_garden.json` | P2 |
| CREATE | `config/verticals/sports.json` | P2 |
| EDIT | `src/app/services/orchestrator.py` | P0 |
| EDIT | `src/app/services/tier_router.py` | P0 |
| REFACTOR | `src/app/services/expanded_rules.py` | P0 |
| REFACTOR | `src/app/services/rule_store.py` | P0 |

### Phase 2 Files (16 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/ml/signal_fusion.py` | P0 |
| CREATE | `src/app/ml/feature_extractor.py` | P0 |
| CREATE | `src/app/ml/calibration.py` | P0 |
| CREATE | `src/app/ml/training/fusion_trainer.py` | P1 |
| CREATE | `src/app/ml/training/active_learning.py` | P1 |
| CREATE | `src/app/services/parallel_executor.py` | P0 |
| CREATE | `src/app/services/signal_collector.py` | P0 |
| CREATE | `src/app/services/cache_manager.py` | P0 |
| CREATE | `src/app/schemas/ml_signals.py` | P0 |
| CREATE | `models/signal_fusion.pkl` | P1 |
| CREATE | `config/ml/fusion_features.json` | P0 |
| CREATE | `config/ml/calibration_params.json` | P0 |
| EDIT | `src/app/services/orchestrator.py` | P0 |
| EDIT | `src/app/services/cv_tiered.py` | P0 |
| REFACTOR | `src/app/services/parallel_agent_executor.py` | P0 |
| REFACTOR | `src/app/services/confidence_calibration.py` | P0 |

### Phase 3 Files (22 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/cv/roi_detector.py` | P0 |
| CREATE | `src/app/cv/ocr_pipeline.py` | P0 |
| CREATE | `src/app/cv/ocr_postprocess.py` | P0 |
| CREATE | `src/app/cv/barcode_decoder.py` | P0 |
| CREATE | `src/app/cv/image_normalizer.py` | P0 |
| CREATE | `src/app/cv/roi_cropper.py` | P0 |
| CREATE | `src/app/cv/evidence_writer.py` | P0 |
| CREATE | `src/app/cv/model_registry.py` | P0 |
| CREATE | `src/app/cv/warmup.py` | P1 |
| CREATE | `src/app/schemas/cv_artifacts.py` | P0 |
| CREATE | `src/app/routers/cv_evidence.py` | P0 |
| CREATE | `models/yolo_roi_v1.pt` | P0 |
| CREATE | `config/cv/roi_classes.json` | P0 |
| CREATE | `config/cv/ocr_patterns.json` | P0 |
| CREATE | `config/cv/vendor_dictionaries.json` | P1 |
| CREATE | `data/training/roi_annotations/` | P1 |
| EDIT | `src/app/services/cv_tiered.py` | P0 |
| EDIT | `src/app/services/cv_ocr.py` | P0 |
| EDIT | `src/app/routers/cv.py` | P0 |
| REFACTOR | `src/app/services/cv_object_detector.py` | P0 |
| REFACTOR | `src/app/services/cv_provider.py` | P0 |
| REFACTOR | `src/app/services/image_intake.py` | P0 |

### Phase 4 Files (20 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/cv/damage_classifier.py` | P0 |
| CREATE | `src/app/cv/damage_segmenter.py` | P2 |
| CREATE | `src/app/cv/visual_embedder.py` | P1 |
| CREATE | `src/app/cv/catalog_matcher.py` | P1 |
| CREATE | `src/app/cv/category_detector.py` | P1 |
| CREATE | `src/app/fraud/reuse_detector.py` | P0 |
| CREATE | `src/app/fraud/manipulation_detector.py` | P0 |
| CREATE | `src/app/fraud/inconsistency_checker.py` | P0 |
| CREATE | `src/app/fraud/behavioral_scorer.py` | P0 |
| CREATE | `src/app/fraud/ensemble.py` | P0 |
| CREATE | `src/app/schemas/fraud_signals.py` | P0 |
| CREATE | `src/app/routers/fraud_analysis.py` | P1 |
| CREATE | `models/damage_classifier_v1.pkl` | P0 |
| CREATE | `models/visual_embedder.pkl` | P1 |
| CREATE | `config/fraud/known_hashes.db` | P0 |
| CREATE | `config/fraud/behavioral_thresholds.json` | P0 |
| EDIT | `src/app/services/cv_tier2_pipeline.py` | P0 |
| EDIT | `src/app/services/fraud_scorer.py` | P0 |
| REFACTOR | `src/app/services/cv_damage_classifier.py` | P0 |
| REFACTOR | `src/app/services/image_forensics.py` | P0 |

### Phase 5 Files (26 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/inventory/canonical_model.py` | P0 |
| CREATE | `src/app/inventory/sync_engine.py` | P0 |
| CREATE | `src/app/inventory/adapters/shopify.py` | P0 |
| CREATE | `src/app/inventory/adapters/bigcommerce.py` | P1 |
| CREATE | `src/app/inventory/adapters/custom.py` | P1 |
| CREATE | `src/app/inventory/adapters/base.py` | P0 |
| CREATE | `src/app/inventory/returns_validator.py` | P0 |
| CREATE | `src/app/inventory/reorder_agent.py` | P1 |
| CREATE | `src/app/erp/edi_handler.py` | P1 |
| CREATE | `src/app/erp/connectors/sap.py` | P2 |
| CREATE | `src/app/erp/connectors/netsuite.py` | P2 |
| CREATE | `src/app/erp/connectors/base.py` | P1 |
| CREATE | `src/app/erp/message_parser.py` | P1 |
| CREATE | `src/app/erp/conflict_resolver.py` | P1 |
| CREATE | `src/app/schemas/inventory_sync.py` | P0 |
| CREATE | `src/app/schemas/edi_messages.py` | P1 |
| CREATE | `src/app/routers/inventory_sync.py` | P0 |
| CREATE | `src/app/routers/erp_webhooks.py` | P1 |
| CREATE | `connectors/shopify/inventory.py` | P0 |
| CREATE | `connectors/bigcommerce/inventory.py` | P1 |
| CREATE | `config/erp/edi_mappings.json` | P1 |
| CREATE | `config/erp/sync_policies.json` | P0 |
| EDIT | `src/app/services/inventory_agent.py` | P0 |
| EDIT | `src/app/services/warehouse_verification.py` | P0 |
| REFACTOR | `src/app/services/erp_edi.py` | P1 |
| REFACTOR | `connectors/shopify/` | P0 |

### Phase 6 Files (22 files)

| Type | Path | Priority |
|------|------|----------|
| CREATE | `src/app/eval/offline_runner.py` | P0 |
| CREATE | `src/app/eval/eval_sets/` | P0 |
| CREATE | `src/app/eval/metrics.py` | P0 |
| CREATE | `src/app/eval/replay.py` | P0 |
| CREATE | `src/app/eval/ab_test.py` | P1 |
| CREATE | `src/app/monitoring/drift_detector.py` | P0 |
| CREATE | `src/app/monitoring/cost_tracker.py` | P0 |
| CREATE | `src/app/monitoring/latency_tracker.py` | P0 |
| CREATE | `src/app/monitoring/guardrails.py` | P0 |
| CREATE | `src/app/monitoring/alerts.py` | P1 |
| CREATE | `src/app/monitoring/dashboards/cost.json` | P1 |
| CREATE | `src/app/monitoring/dashboards/accuracy.json` | P1 |
| CREATE | `src/app/training/feedback_loop.py` | P0 |
| CREATE | `src/app/training/data_exporter.py` | P1 |
| CREATE | `src/app/routers/eval.py` | P0 |
| CREATE | `src/app/routers/monitoring.py` | P0 |
| CREATE | `config/eval/thresholds.json` | P0 |
| CREATE | `config/monitoring/alerts.json` | P1 |
| EDIT | `src/app/observability/metrics.py` | P0 |
| EDIT | `src/app/services/decision_log.py` | P0 |
| REFACTOR | `src/app/eval/runner.py` | P0 |
| REFACTOR | `src/app/analytics/ragas.py` | P0 |

---

## 11. Test Coverage Matrix

### Unit Tests by Phase

| Phase | Test Directory | Test Count | Coverage Target |
|-------|----------------|------------|-----------------|
| 0 | `tests/rules/` | 6 | 90% |
| 0 | `tests/models/` | 2 | 85% |
| 1 | `tests/rules/` | 5 | 90% |
| 1 | `tests/policy/` | 3 | 85% |
| 2 | `tests/ml/` | 4 | 80% |
| 2 | `tests/services/` | 3 | 85% |
| 3 | `tests/cv/` | 8 | 85% |
| 4 | `tests/cv/` | 5 | 85% |
| 4 | `tests/fraud/` | 5 | 85% |
| 5 | `tests/inventory/` | 5 | 85% |
| 5 | `tests/erp/` | 4 | 80% |
| 6 | `tests/eval/` | 4 | 80% |
| 6 | `tests/monitoring/` | 5 | 80% |

### Integration Tests by Phase

| Phase | Test File | Focus |
|-------|-----------|-------|
| 0 | `tests/integration/test_tier0_gate.py` | Rules gate ML |
| 1 | `tests/integration/test_rule_engine.py` | Rule evaluation |
| 2 | `tests/integration/test_tiered_routing.py` | Signal fusion |
| 3 | `tests/integration/test_cv_full_pipeline.py` | End-to-end CV |
| 4 | `tests/integration/test_fraud_detection.py` | Fraud ensemble |
| 5 | `tests/integration/test_inventory_e2e.py` | Inventory sync |
| 6 | `tests/integration/test_eval_pipeline.py` | Evaluation loop |

### Playwright Tests by Phase

| Phase | Test File | User Flow |
|-------|-----------|-----------|
| 0 | `returns_quality_gate.spec.ts` | Upload blocked by quality |
| 1 | `admin_rules_management.spec.ts` | Admin manages rules |
| 1 | `vertical_switching.spec.ts` | Switch vertical packs |
| 2 | `decision_confidence.spec.ts` | Confidence display |
| 3 | `returns_image_upload.spec.ts` | Full upload flow |
| 3 | `cv_evidence_display.spec.ts` | Evidence bundle UI |
| 4 | `fraud_detection_ui.spec.ts` | Fraud alerts |
| 4 | `damage_classification_display.spec.ts` | Damage results |
| 5 | `inventory_dashboard.spec.ts` | Inventory view |
| 5 | `reorder_alerts.spec.ts` | Reorder notifications |
| 6 | `eval_dashboard.spec.ts` | Eval metrics |
| 6 | `cost_dashboard.spec.ts` | Cost tracking |

### Test Commands by Phase

```bash
# Phase 0
pytest tests/rules/test_image_quality.py tests/rules/test_eligibility.py tests/rules/test_required_views.py tests/rules/test_hash_reuse.py tests/rules/test_barcode_decode.py tests/rules/test_tier0_gate.py tests/models/test_return_case.py tests/models/test_evidence_bundle.py -v
npx playwright test tests/playwright/returns_quality_gate.spec.ts

# Phase 1
pytest tests/rules/test_engine.py tests/rules/test_sku_blacklist.py tests/rules/test_serial_patterns.py tests/rules/test_fraud_heuristics.py tests/rules/test_escalation_triggers.py tests/policy/ tests/api/test_rules_admin.py tests/integration/test_rule_engine.py -v
npx playwright test tests/playwright/admin_rules_management.spec.ts tests/playwright/vertical_switching.spec.ts

# Phase 2
pytest tests/ml/ tests/services/test_parallel_executor.py tests/services/test_signal_collector.py tests/services/test_cache_manager.py tests/integration/test_tiered_routing.py -v
npx playwright test tests/playwright/decision_confidence.spec.ts

# Phase 3
pytest tests/cv/test_roi_detector.py tests/cv/test_ocr_pipeline.py tests/cv/test_barcode_decoder.py tests/cv/test_image_normalizer.py tests/cv/test_roi_cropper.py tests/cv/test_evidence_writer.py tests/cv/test_model_registry.py tests/api/test_cv_evidence.py tests/integration/test_cv_full_pipeline.py -v
npx playwright test tests/playwright/returns_image_upload.spec.ts tests/playwright/cv_evidence_display.spec.ts

# Phase 4
pytest tests/cv/test_damage_classifier.py tests/cv/test_visual_embedder.py tests/cv/test_catalog_matcher.py tests/fraud/ tests/api/test_fraud_analysis.py tests/integration/test_fraud_detection.py -v
npx playwright test tests/playwright/fraud_detection_ui.spec.ts tests/playwright/damage_classification_display.spec.ts

# Phase 5
pytest tests/inventory/ tests/erp/ tests/api/test_inventory_sync.py tests/api/test_erp_webhooks.py tests/integration/test_inventory_e2e.py -v
npx playwright test tests/playwright/inventory_dashboard.spec.ts tests/playwright/reorder_alerts.spec.ts

# Phase 6
pytest tests/eval/ tests/monitoring/ tests/training/ tests/api/test_eval_api.py tests/api/test_monitoring_api.py -v
npx playwright test tests/playwright/eval_dashboard.spec.ts tests/playwright/cost_dashboard.spec.ts

# Full regression
pytest tests/ -v --tb=short -x
npx playwright test tests/playwright/
```

---

## 12. Quick Reference: Phase Checklist

### Phase 0: Core Foundation ✅ Checklist

- [x] Create ReturnCase, EvidenceBundle, HumanReviewTask schemas
- [x] Create ORM models for new schemas
- [x] Create image quality rules (blur, size, format)
- [x] Create eligibility rules (return window, blacklist)
- [x] Create required views checker per vertical
- [x] Create perceptual hash reuse detection
- [x] Create fast barcode/QR decode
- [x] Create Tier 0 decision gate
- [ ] Run database migrations
- [x] Configure feature flags
- [ ] Run pytest: `tests/rules/`, `tests/models/`
- [ ] Run playwright: `returns_quality_gate.spec.ts`

### Phase 1: Enhanced Rules ✅ Checklist

- [ ] Create central rule engine with priorities
- [ ] Create SKU blacklist rules
- [ ] Create return window rules
- [ ] Create serial pattern validators
- [ ] Create threshold gates
- [ ] Create fraud heuristic rules
- [ ] Create escalation trigger rules
- [ ] Create vertical pack loader
- [ ] Create taxonomy definitions
- [ ] Create rules admin API
- [ ] Configure vertical packs (electronics, fashion)
- [ ] Run pytest: `tests/rules/`, `tests/policy/`
- [ ] Run playwright: `admin_rules_management.spec.ts`

### Phase 2: Small ML ✅ Checklist

- [ ] Create signal fusion scorer
- [ ] Create feature extractor
- [ ] Create confidence calibration
- [ ] Create fusion model trainer
- [ ] Create active learning loop
- [x] Create parallel executor
- [ ] Create signal collector
- [ ] Create cache manager
- [ ] Train initial fusion model
- [ ] Configure calibration
- [ ] Run pytest: `tests/ml/`, `tests/services/`
- [ ] Run playwright: `decision_confidence.spec.ts`

### Phase 3: CV/OCR Pipeline ✅ Checklist

- [ ] Create ROI detector (YOLO)
- [ ] Create OCR pipeline (detection + recognition)
- [ ] Create OCR post-processing
- [ ] Create barcode decoder
- [ ] Create image normalizer
- [ ] Create ROI cropper
- [ ] Create evidence writer
- [ ] Create model registry
- [ ] Train/fine-tune YOLO ROI model
- [ ] Configure ROI classes
- [ ] Configure OCR patterns
- [ ] Run pytest: `tests/cv/`
- [ ] Run playwright: `returns_image_upload.spec.ts`

### Phase 4: Advanced Models ✅ Checklist

- [ ] Create damage classifier
- [ ] Create damage segmenter (optional)
- [ ] Create visual embedder
- [ ] Create catalog matcher
- [ ] Create reuse detector
- [ ] Create manipulation detector
- [ ] Create inconsistency checker
- [ ] Create behavioral scorer
- [ ] Create fraud ensemble
- [ ] Train damage classifier
- [ ] Build known fraud hash DB
- [ ] Run pytest: `tests/cv/`, `tests/fraud/`
- [ ] Run playwright: `fraud_detection_ui.spec.ts`

### Phase 5: Inventory/ERP ✅ Checklist

- [ ] Create canonical inventory model
- [ ] Create sync engine
- [ ] Create Shopify adapter
- [ ] Create BigCommerce adapter
- [ ] Create base adapter interface
- [ ] Create returns validator
- [ ] Create reorder agent
- [ ] Create EDI handler
- [ ] Create ERP connectors
- [ ] Create conflict resolver
- [ ] Configure sync policies
- [ ] Run pytest: `tests/inventory/`, `tests/erp/`
- [ ] Run playwright: `inventory_dashboard.spec.ts`

### Phase 6: Evaluation ✅ Checklist

- [ ] Create offline evaluation runner
- [ ] Create evaluation datasets per vertical
- [ ] Create eval metrics
- [ ] Create decision replay
- [ ] Create A/B test framework
- [ ] Create drift detector
- [ ] Create cost tracker
- [ ] Create latency tracker
- [ ] Create runtime guardrails
- [ ] Create alert definitions
- [ ] Create feedback loop
- [ ] Create training data exporter
- [ ] Run pytest: `tests/eval/`, `tests/monitoring/`
- [ ] Run playwright: `eval_dashboard.spec.ts`

---

## Summary: Cost-Pragmatic Priorities

| Priority | What | Why |
|----------|------|-----|
| **P0** | Rules (Tier 0) | Gate 60-80% of requests before ML |
| **P1** | Signal Fusion | Combine cheap signals, escalate smart |
| **P2** | YOLO ROI | One model for multiple downstream tasks |
| **P3** | OCR Pipeline | Extract structured data cheaply |
| **P4** | Damage Classifier | Classify on cropped ROIs |
| **P5** | Fraud Ensemble | Layer signals, not heavy models |
| **P6** | Inventory Sync | Real data for validation |
| **P7** | Evaluation Loop | Continuous improvement |

**Key Principle**: Every expensive operation should be gated by a cheap check. Rules first, then small ML, then escalate.

---

*Document generated: February 2026*
*Version: 1.0.0*
