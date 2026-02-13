# Computer Vision Complaint Triage - MVP Options

**Generated:** 2026-01-23
**Status:** Implementation Options for MVP Release

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Three Implementation Options](#three-implementation-options)
3. [User Flows](#user-flows)
4. [Fraud Detection Strategies](#fraud-detection-strategies)
5. [Refund & Return Shipping Workflows](#refund--return-shipping-workflows)
6. [Customer History Integration](#customer-history-integration)
7. [NLP Agent Notification Integration](#nlp-agent-notification-integration)
8. [Disclaimers & User Messaging](#disclaimers--user-messaging)
9. [Technical Implementation](#technical-implementation)
10. [Comparison Matrix](#comparison-matrix)

---

## Executive Summary

This document outlines three options for implementing computer vision (CV) assisted complaint triage in ShopSquire. Each option balances capability, cost, and time-to-ship.

| Option | Time to Ship | Monthly Cost | Fraud Detection | Best For |
|--------|--------------|--------------|-----------------|----------|
| **Option 1: Cloud API Only** | 1-2 weeks | $50-200 | Basic | MVP launch |
| **Option 2: Custom Classifier** | 3-4 weeks | $100-400 | Moderate | Growth stage |
| **Option 3: Full Fraud Stack** | 6-8 weeks | $300-800 | Advanced | Enterprise |

---

## Three Implementation Options

### Option 1: Cloud API Only (Fastest MVP)

**Philosophy:** Use pre-built cloud APIs with zero custom training. Accept lower accuracy in exchange for speed to market.

#### What You Get

| Capability | Provider | Accuracy | Notes |
|------------|----------|----------|-------|
| General object detection | Google Vision | 85-90% | Detects "laptop", "screen", "crack" |
| OCR (serial numbers) | Google Vision | 95%+ | Extract text from receipts/labels |
| Safe search (inappropriate content) | Google Vision | 90%+ | Filter out non-complaint images |
| Basic damage keywords | Label matching | 70-75% | Match detected labels to damage types |

#### Architecture

```
Customer Image
      │
      ▼
┌─────────────────────────────────────┐
│     Google Vision API               │
│     (No custom training)            │
├─────────────────────────────────────┤
│  Returns:                           │
│  - labels: ["laptop", "cracked",    │
│             "screen", "damaged"]    │
│  - text: "SN-ABC123"                │
│  - safe_search: PASS                │
└─────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────┐
│     Label Mapping Rules             │
│     (Your business logic)           │
├─────────────────────────────────────┤
│  IF "crack" OR "broken" in labels   │
│     → damage_type = "physical"      │
│  IF "screen" in labels              │
│     → component = "display"         │
│  ELSE                               │
│     → needs_human_review = true     │
└─────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────┐
│     Enriched Ticket                 │
│     + Disclaimer shown to user      │
└─────────────────────────────────────┘
```

#### Pros & Cons

| Pros | Cons |
|------|------|
| Ship in 1-2 weeks | Lower accuracy (70-75%) |
| No training data needed | No custom damage categories |
| $0.0015/image cost | Limited fraud detection |
| Zero ML expertise required | Generic labels, not retail-specific |

#### Code Sample

```python
# src/app/services/cv_triage_basic.py

from google.cloud import vision
from typing import Optional
import re

class BasicCVTriage:
    """
    Option 1: Cloud API only - no custom training.
    Uses label matching for damage classification.
    """

    DAMAGE_KEYWORDS = {
        "physical": ["crack", "cracked", "broken", "dent", "scratch", "shattered"],
        "cosmetic": ["scuff", "mark", "stain", "discolor"],
        "functional": ["error", "screen", "display", "black", "dead"],
        "packaging": ["box", "package", "torn", "crushed", "wet"],
    }

    COMPONENT_KEYWORDS = {
        "display": ["screen", "monitor", "lcd", "panel"],
        "chassis": ["case", "body", "frame", "hinge"],
        "keyboard": ["keyboard", "keys", "trackpad"],
        "power": ["charger", "battery", "adapter", "cable"],
    }

    def __init__(self):
        self.client = vision.ImageAnnotatorClient()

    async def analyze(self, image_bytes: bytes) -> dict:
        """Analyze image using only pre-built cloud APIs."""

        image = vision.Image(content=image_bytes)

        # Get labels, text, and safe search in parallel
        response = self.client.annotate_image({
            "image": image,
            "features": [
                {"type_": vision.Feature.Type.LABEL_DETECTION, "max_results": 20},
                {"type_": vision.Feature.Type.TEXT_DETECTION},
                {"type_": vision.Feature.Type.SAFE_SEARCH_DETECTION},
            ]
        })

        labels = [label.description.lower() for label in response.label_annotations]
        confidence_scores = {
            label.description.lower(): label.score
            for label in response.label_annotations
        }

        # Extract text (serial numbers, receipts)
        extracted_text = ""
        if response.text_annotations:
            extracted_text = response.text_annotations[0].description

        # Safe search check
        safe = response.safe_search_annotation
        is_appropriate = (
            safe.adult < 3 and safe.violence < 3 and safe.racy < 3
        )

        # Map labels to damage type using keywords
        damage_type = self._classify_damage(labels)
        component = self._identify_component(labels)
        serial_number = self._extract_serial(extracted_text)

        # Calculate confidence based on keyword matches
        confidence = self._calculate_confidence(labels, damage_type)

        return {
            "status": "analyzed",
            "damage_type": damage_type,
            "component": component,
            "severity": self._estimate_severity(labels, confidence),
            "confidence": confidence,
            "serial_number": serial_number,
            "extracted_text": extracted_text[:500],  # Truncate
            "raw_labels": labels[:10],
            "is_appropriate_content": is_appropriate,
            "needs_human_review": confidence < 0.6 or not is_appropriate,
            "ai_disclaimer": "preliminary",  # Triggers disclaimer in UI
        }

    def _classify_damage(self, labels: list) -> str:
        """Map detected labels to damage category."""
        for damage_type, keywords in self.DAMAGE_KEYWORDS.items():
            if any(kw in " ".join(labels) for kw in keywords):
                return damage_type
        return "unknown"

    def _identify_component(self, labels: list) -> Optional[str]:
        """Identify which component is damaged."""
        label_text = " ".join(labels)
        for component, keywords in self.COMPONENT_KEYWORDS.items():
            if any(kw in label_text for kw in keywords):
                return component
        return None

    def _extract_serial(self, text: str) -> Optional[str]:
        """Extract serial number patterns from OCR text."""
        patterns = [
            r'S/?N[:\s]*([A-Z0-9]{6,20})',  # SN: ABC123
            r'Serial[:\s]*([A-Z0-9]{6,20})',  # Serial: ABC123
            r'([A-Z]{2,3}[0-9]{6,12})',  # Common format: ABC123456
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _calculate_confidence(self, labels: list, damage_type: str) -> float:
        """Estimate confidence based on keyword match strength."""
        if damage_type == "unknown":
            return 0.3

        keywords = self.DAMAGE_KEYWORDS.get(damage_type, [])
        matches = sum(1 for kw in keywords if kw in " ".join(labels))

        # More keyword matches = higher confidence
        return min(0.5 + (matches * 0.15), 0.85)

    def _estimate_severity(self, labels: list, confidence: float) -> str:
        """Estimate damage severity."""
        severe_indicators = ["shattered", "destroyed", "broken", "dead"]
        if any(ind in " ".join(labels) for ind in severe_indicators):
            return "critical"
        elif confidence > 0.7:
            return "major"
        elif confidence > 0.5:
            return "minor"
        return "undetermined"
```

---

### Option 2: Custom Classifier (Balanced MVP)

**Philosophy:** Train a custom model on YOUR product categories and damage types. Better accuracy, moderate effort.

#### What You Get

| Capability | Implementation | Accuracy | Notes |
|------------|----------------|----------|-------|
| Custom damage classification | AutoML Vision | 85-92% | Trained on your images |
| Product category detection | Custom labels | 88-95% | Your SKU categories |
| Severity grading | Multi-class model | 80-85% | minor/major/critical |
| OCR (serial numbers) | Google Vision | 95%+ | Same as Option 1 |
| Basic fraud signals | Rule-based | 70-80% | Image metadata analysis |

#### Training Data Requirements

| Category | Images Needed | Annotation Type |
|----------|---------------|-----------------|
| Screen damage | 100+ | Bounding box + severity |
| Physical damage (dents) | 100+ | Bounding box + severity |
| Packaging damage | 50+ | Image-level label |
| Correct/undamaged | 200+ | Image-level "ok" |
| Wrong item | 50+ | Image-level label |
| Fraud examples | 30+ | Image-level "suspicious" |

**Total: ~530 images minimum** (collect from past complaints + staged photos)

#### Architecture

```
Customer Image
      │
      ▼
┌─────────────────────────────────────┐
│     Pre-processing                  │
│     - Resize to 640x640             │
│     - EXIF metadata extraction      │
│     - Perceptual hash generation    │
└─────────────────────────────────────┘
      │
      ├──────────────────────────────────┐
      ▼                                  ▼
┌─────────────────────┐    ┌─────────────────────────┐
│  Custom AutoML      │    │  Google Vision API      │
│  Damage Classifier  │    │  (OCR + Safe Search)    │
├─────────────────────┤    ├─────────────────────────┤
│  Returns:           │    │  Returns:               │
│  - damage_type      │    │  - extracted_text       │
│  - severity         │    │  - is_appropriate       │
│  - confidence       │    │  - general_labels       │
└─────────────────────┘    └─────────────────────────┘
      │                                  │
      └──────────────┬───────────────────┘
                     ▼
┌─────────────────────────────────────┐
│     Fraud Signal Analysis           │
├─────────────────────────────────────┤
│  - EXIF timestamp vs complaint date │
│  - Image similarity to known frauds │
│  - Metadata anomalies               │
│  - Purchase history cross-check     │
└─────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────┐
│     Combined Scoring & Routing      │
└─────────────────────────────────────┘
```

#### Pros & Cons

| Pros | Cons |
|------|------|
| 85-92% accuracy | Requires 500+ training images |
| Custom to your products | 3-4 weeks to ship |
| Basic fraud detection | AutoML costs ($3-5/training hour) |
| Severity grading built-in | Need annotation effort |

#### Code Sample

```python
# src/app/services/cv_triage_custom.py

from google.cloud import aiplatform
from google.cloud import vision
from PIL import Image
import imagehash
from datetime import datetime, timedelta
from typing import Optional, Tuple
import io

class CustomCVTriage:
    """
    Option 2: Custom classifier with fraud signals.
    Requires trained AutoML model.
    """

    def __init__(self, model_endpoint: str):
        self.model_endpoint = model_endpoint
        self.vision_client = vision.ImageAnnotatorClient()
        self.fraud_hash_db = set()  # Load known fraud image hashes

    async def analyze(self, image_bytes: bytes, complaint_date: datetime) -> dict:
        """Full analysis with custom model + fraud detection."""

        # 1. Custom damage classification
        damage_result = await self._classify_damage(image_bytes)

        # 2. OCR and safe search (same as Option 1)
        ocr_result = await self._extract_text_and_check(image_bytes)

        # 3. Fraud signal analysis
        fraud_signals = await self._analyze_fraud_signals(
            image_bytes, complaint_date
        )

        # 4. Combine results
        combined_confidence = self._combine_confidence(
            damage_result["confidence"],
            fraud_signals["trust_score"]
        )

        return {
            "status": "analyzed",
            "damage_type": damage_result["damage_type"],
            "damage_location": damage_result.get("location"),
            "severity": damage_result["severity"],
            "confidence": combined_confidence,
            "serial_number": ocr_result.get("serial_number"),
            "extracted_text": ocr_result.get("text", "")[:500],
            "is_appropriate_content": ocr_result["is_appropriate"],

            # Fraud signals
            "fraud_risk": fraud_signals["risk_level"],
            "fraud_signals": fraud_signals["signals"],
            "trust_score": fraud_signals["trust_score"],

            # Routing
            "needs_human_review": (
                combined_confidence < 0.7 or
                fraud_signals["risk_level"] in ["medium", "high"]
            ),
            "suggested_routing": self._determine_routing(
                damage_result, fraud_signals
            ),
            "ai_disclaimer": "assisted",
        }

    async def _classify_damage(self, image_bytes: bytes) -> dict:
        """Call custom AutoML model for damage classification."""

        endpoint = aiplatform.Endpoint(self.model_endpoint)

        # Prepare image for prediction
        import base64
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        response = endpoint.predict(instances=[{"content": encoded}])

        prediction = response.predictions[0]

        return {
            "damage_type": prediction["displayNames"][0],
            "severity": self._map_severity(prediction["displayNames"]),
            "confidence": max(prediction["confidences"]),
            "location": prediction.get("boundingBox"),  # If detection model
        }

    async def _analyze_fraud_signals(
        self,
        image_bytes: bytes,
        complaint_date: datetime
    ) -> dict:
        """Analyze image for fraud indicators."""

        signals = []
        trust_score = 1.0

        # 1. Check EXIF metadata
        exif_result = self._check_exif(image_bytes, complaint_date)
        if exif_result["suspicious"]:
            signals.append(exif_result["reason"])
            trust_score -= 0.2

        # 2. Check for known fraud image hash
        img_hash = self._compute_hash(image_bytes)
        if img_hash in self.fraud_hash_db:
            signals.append("image_matches_known_fraud")
            trust_score -= 0.5

        # 3. Check for stock photo indicators
        stock_indicators = self._check_stock_photo(image_bytes)
        if stock_indicators["is_stock"]:
            signals.append("possible_stock_photo")
            trust_score -= 0.3

        # 4. Check image manipulation (basic)
        manipulation = self._check_manipulation(image_bytes)
        if manipulation["edited"]:
            signals.append(f"image_edited: {manipulation['reason']}")
            trust_score -= 0.15

        # Determine risk level
        if trust_score < 0.5:
            risk_level = "high"
        elif trust_score < 0.7:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_level": risk_level,
            "trust_score": max(0, trust_score),
            "signals": signals,
        }

    def _check_exif(
        self,
        image_bytes: bytes,
        complaint_date: datetime
    ) -> dict:
        """Check EXIF data for suspicious patterns."""

        try:
            img = Image.open(io.BytesIO(image_bytes))
            exif = img._getexif()

            if not exif:
                return {"suspicious": False, "reason": None}

            # Check if photo date is way before complaint
            date_taken = exif.get(36867)  # DateTimeOriginal
            if date_taken:
                photo_date = datetime.strptime(date_taken, "%Y:%m:%d %H:%M:%S")
                days_diff = (complaint_date - photo_date).days

                if days_diff > 30:
                    return {
                        "suspicious": True,
                        "reason": f"photo_taken_{days_diff}_days_before_complaint"
                    }
                elif days_diff < 0:
                    return {
                        "suspicious": True,
                        "reason": "photo_date_after_complaint_date"
                    }

            return {"suspicious": False, "reason": None}

        except Exception:
            return {"suspicious": False, "reason": None}

    def _compute_hash(self, image_bytes: bytes) -> str:
        """Compute perceptual hash for image similarity."""
        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(img))

    def _check_stock_photo(self, image_bytes: bytes) -> dict:
        """Basic check for stock photo characteristics."""
        # In production: use reverse image search API
        # For MVP: check for watermarks, perfect lighting, etc.

        img = Image.open(io.BytesIO(image_bytes))

        # Stock photos often have perfect dimensions
        suspicious_ratios = [(16, 9), (4, 3), (3, 2), (1, 1)]
        width, height = img.size

        for w, h in suspicious_ratios:
            if abs(width/height - w/h) < 0.01 and width > 2000:
                return {"is_stock": True, "reason": "perfect_stock_dimensions"}

        return {"is_stock": False, "reason": None}

    def _check_manipulation(self, image_bytes: bytes) -> dict:
        """Basic image manipulation detection."""

        img = Image.open(io.BytesIO(image_bytes))

        # Check for signs of editing software
        info = img.info

        if "photoshop" in str(info).lower():
            return {"edited": True, "reason": "photoshop_metadata"}

        if "gimp" in str(info).lower():
            return {"edited": True, "reason": "gimp_metadata"}

        return {"edited": False, "reason": None}

    def _determine_routing(self, damage: dict, fraud: dict) -> str:
        """Determine where to route based on analysis."""

        if fraud["risk_level"] == "high":
            return "fraud_review_team"

        if damage["severity"] == "critical":
            return "senior_support"

        if fraud["risk_level"] == "medium":
            return "supervisor_review"

        if damage["confidence"] > 0.85:
            return "auto_process"

        return "standard_queue"
```

---

### Option 3: Full Fraud Detection Stack (Enterprise)

**Philosophy:** Comprehensive fraud prevention with purchase verification, return history analysis, and advanced image forensics.

#### What You Get

| Capability | Implementation | Accuracy | Notes |
|------------|----------------|----------|-------|
| Custom damage classification | AutoML Vision | 90-95% | More training data |
| Product verification | Embedding similarity | 92-97% | Verify item matches purchase |
| Purchase history cross-check | Database lookup | 99%+ | Did they actually buy this? |
| Return pattern analysis | ML model | 85-90% | Detect serial returners |
| Image forensics | Specialized APIs | 88-93% | Manipulation, stock photo detection |
| Reverse image search | TinEye/Google API | 95%+ | Find if image from internet |

#### Architecture

```
Customer Complaint Submission
      │
      ├── Image(s)
      ├── Text description
      ├── Customer ID (or guest receipt)
      └── Claimed order/product
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    INTAKE VALIDATION                         │
├─────────────────────────────────────────────────────────────┤
│  1. Is customer logged in or have valid receipt?            │
│  2. Does claimed order exist in our system?                 │
│  3. Is product within return window?                        │
│  4. Basic image format validation                           │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    PARALLEL ANALYSIS                         │
├──────────────────┬──────────────────┬───────────────────────┤
│  CV Analysis     │  Fraud Analysis  │  Customer Analysis    │
├──────────────────┼──────────────────┼───────────────────────┤
│  - Damage type   │  - EXIF check    │  - Purchase verified  │
│  - Severity      │  - Hash lookup   │  - Return history     │
│  - Product ID    │  - Stock photo   │  - Account age        │
│  - Serial OCR    │  - Manipulation  │  - Chargeback history │
│  - Condition     │  - Reverse search│  - Loyalty tier       │
└──────────────────┴──────────────────┴───────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    PRODUCT VERIFICATION                      │
├─────────────────────────────────────────────────────────────┤
│  Compare submitted image to:                                 │
│  - Original product photo from order                        │
│  - Expected product appearance for SKU                      │
│  - Serial number matches purchase record                    │
│                                                              │
│  Flags: wrong_product, different_sku, serial_mismatch       │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    FRAUD SCORING ENGINE                      │
├─────────────────────────────────────────────────────────────┤
│  Input signals:                                              │
│  - CV confidence score                                       │
│  - Fraud signal count                                        │
│  - Customer trust score                                      │
│  - Product verification score                                │
│  - Return history risk                                       │
│                                                              │
│  Output: fraud_probability (0-1), risk_category             │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                    DECISION ENGINE                           │
├─────────────────────────────────────────────────────────────┤
│  AUTO-APPROVE if:                                            │
│  - fraud_probability < 0.2                                   │
│  - customer_tier = "gold" or "platinum"                     │
│  - damage_confidence > 0.9                                   │
│  - within_policy = true                                      │
│                                                              │
│  ESCALATE if:                                                │
│  - fraud_probability > 0.5                                   │
│  - high_value_item = true                                    │
│  - serial_mismatch = true                                    │
│                                                              │
│  HUMAN REVIEW otherwise                                      │
└─────────────────────────────────────────────────────────────┘
```

#### Pros & Cons

| Pros | Cons |
|------|------|
| 90-95% accuracy | 6-8 weeks to build |
| Comprehensive fraud prevention | $300-800/month operational cost |
| Purchase verification | Requires order system integration |
| Return abuse detection | Complex ML pipeline |
| Enterprise-grade audit trail | Needs dedicated ML ops |

---

## User Flows

### Flow 1: Logged-In Customer Complaint

```
┌─────────────────────────────────────────────────────────────┐
│  LOGGED-IN CUSTOMER - DAMAGE COMPLAINT                       │
└─────────────────────────────────────────────────────────────┘

[Customer Dashboard]
      │
      ▼
┌─────────────────┐
│ "Report Issue"  │
│ button clicked  │
└─────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: SELECT ORDER                                        │
├─────────────────────────────────────────────────────────────┤
│  "Which order has an issue?"                                 │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Order #12345 - Jan 15, 2026                         │    │
│  │ Dell XPS 15 Laptop - $1,299.00                      │    │
│  │ [Select this order]                                 │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Order #12340 - Jan 10, 2026                         │    │
│  │ Laptop Sleeve - $49.00                              │    │
│  │ [Select this order]                                 │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: DESCRIBE ISSUE                                      │
├─────────────────────────────────────────────────────────────┤
│  "What's wrong with your item?"                              │
│                                                              │
│  ○ Arrived damaged                                          │
│  ○ Wrong item received                                      │
│  ○ Item not working                                         │
│  ○ Missing parts                                            │
│  ○ Other                                                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Describe the issue:                                 │    │
│  │ "The screen has a crack in the corner that wasn't  │    │
│  │  there when I opened it. Looks like shipping       │    │
│  │  damage."                                           │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: UPLOAD PHOTOS                                       │
├─────────────────────────────────────────────────────────────┤
│  "Please upload photos of the damage"                        │
│                                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │
│  │  [+]    │  │ IMG_001 │  │ IMG_002 │                     │
│  │  Add    │  │ ✓       │  │ ✓       │                     │
│  │  Photo  │  │         │  │         │                     │
│  └─────────┘  └─────────┘  └─────────┘                     │
│                                                              │
│  Tips:                                                       │
│  • Include close-up of damage                               │
│  • Show serial number label if visible                      │
│  • Include shipping box if damaged                          │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: AI ANALYSIS (Processing...)                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ⏳ Analyzing your photos...                                 │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ✓ Photos received                                   │    │
│  │ ✓ Damage detected: Screen crack                     │    │
│  │ ✓ Serial number extracted: XPS-2026-ABC123         │    │
│  │ ✓ Matches your order                               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ⚠️ Note: Our AI assistant has provided a preliminary       │
│     assessment. A team member will review your case.        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 5: RESOLUTION OPTIONS                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Based on our assessment, here are your options:            │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ⭐ RECOMMENDED                                       │    │
│  │ Full Replacement                                    │    │
│  │ We'll ship a new unit and email a return label     │    │
│  │ Estimated arrival: 3-5 business days               │    │
│  │ [Select Replacement]                                │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Full Refund                                         │    │
│  │ $1,299.00 to original payment method               │    │
│  │ Processing time: 5-7 business days                 │    │
│  │ [Select Refund]                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Speak to Agent                                      │    │
│  │ Need help deciding? Talk to our support team       │    │
│  │ [Chat with Agent]                                   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 6: CONFIRMATION                                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ✅ Your replacement has been approved!                      │
│                                                              │
│  Case #: CASE-2026-45678                                    │
│  Status: Replacement Processing                             │
│                                                              │
│  Next steps:                                                │
│  1. Return label sent to your email                         │
│  2. Ship damaged item within 14 days                        │
│  3. New item ships in 1-2 business days                     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 📧 Email confirmation sent to john@example.com      │    │
│  │ 📱 SMS updates enabled                              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  [Track My Case]  [Return to Dashboard]                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

### Flow 2: Guest Customer (Receipt Only)

```
┌─────────────────────────────────────────────────────────────┐
│  GUEST CUSTOMER - RECEIPT-BASED COMPLAINT                    │
└─────────────────────────────────────────────────────────────┘

[Support Page - "Report Issue"]
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: VERIFY PURCHASE                                     │
├─────────────────────────────────────────────────────────────┤
│  "Let's find your order"                                     │
│                                                              │
│  ○ I have my order number                                   │
│  ● I have my receipt                                        │
│  ○ I paid with credit card (lookup by last 4 digits)       │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Upload receipt photo:                               │    │
│  │                                                     │    │
│  │         ┌─────────┐                                │    │
│  │         │  [+]    │                                │    │
│  │         │  Add    │                                │    │
│  │         │ Receipt │                                │    │
│  │         └─────────┘                                │    │
│  │                                                     │    │
│  │ Or enter order number: [________________]          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  [Continue]                                                  │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: RECEIPT VERIFICATION (AI Processing)                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ⏳ Reading your receipt...                                  │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ✓ Receipt recognized                                │    │
│  │ ✓ Store: ShopSquire Online                         │    │
│  │ ✓ Date: January 15, 2026                           │    │
│  │ ✓ Order #: 12345                                    │    │
│  │ ✓ Item: Dell XPS 15 Laptop                         │    │
│  │ ✓ Amount: $1,299.00                                │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  Is this correct?                                            │
│  [Yes, Continue]  [No, Enter Manually]                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: CONTACT INFORMATION                                 │
├─────────────────────────────────────────────────────────────┤
│  "How can we reach you about this case?"                     │
│                                                              │
│  Email: [_____________________] (required)                  │
│  Phone: [_____________________] (optional)                  │
│                                                              │
│  ☐ Create an account to track this case easily             │
│  ☑ Send me SMS updates                                      │
│                                                              │
│  [Continue]                                                  │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
      (Continue to Steps 2-6 from Flow 1)
```

---

### Flow 3: Fraud Detection Escalation

```
┌─────────────────────────────────────────────────────────────┐
│  FRAUD DETECTION - INTERNAL ESCALATION FLOW                  │
└─────────────────────────────────────────────────────────────┘

[Customer Submits Complaint with Image]
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  AI ANALYSIS DETECTS FRAUD SIGNALS                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  🚨 Fraud Signals Detected:                                  │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Signal                           │ Severity        │    │
│  ├──────────────────────────────────┼─────────────────┤    │
│  │ Photo taken 45 days before       │ ⚠️ Medium       │    │
│  │ complaint date (EXIF)            │                 │    │
│  ├──────────────────────────────────┼─────────────────┤    │
│  │ Image matches known fraud DB     │ 🔴 High         │    │
│  │ (pHash: 89% similarity)          │                 │    │
│  ├──────────────────────────────────┼─────────────────┤    │
│  │ Customer has 5 returns in        │ ⚠️ Medium       │    │
│  │ last 30 days                     │                 │    │
│  ├──────────────────────────────────┼─────────────────┤    │
│  │ Serial number not in purchase    │ 🔴 High         │    │
│  │ record                           │                 │    │
│  └──────────────────────────────────┴─────────────────┘    │
│                                                              │
│  Combined Fraud Score: 0.78 (HIGH RISK)                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  CUSTOMER SEES (Neutral messaging)                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  "Thank you for your submission!"                            │
│                                                              │
│  Your case requires additional review by our team.          │
│  We'll contact you within 24-48 hours.                      │
│                                                              │
│  Case #: CASE-2026-45679                                    │
│                                                              │
│  [Track My Case]                                             │
│                                                              │
│  ───────────────────────────────────────────────────────    │
│  Note: We do NOT tell the customer they're flagged for      │
│  fraud. We simply indicate "additional review needed."      │
│  ───────────────────────────────────────────────────────    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  INTERNAL: FRAUD REVIEW QUEUE                                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  🔴 HIGH PRIORITY - Fraud Review Required                    │
│                                                              │
│  Case: CASE-2026-45679                                      │
│  Customer: john.doe@email.com                               │
│  Claimed Order: #12345 - Dell XPS 15 ($1,299)              │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ AI SUMMARY FOR REVIEWER                             │    │
│  ├─────────────────────────────────────────────────────┤    │
│  │                                                     │    │
│  │ This case has been flagged for potential fraud     │    │
│  │ based on the following signals:                    │    │
│  │                                                     │    │
│  │ 1. IMAGE DATE MISMATCH                             │    │
│  │    The submitted photo was taken on Dec 1, 2025,   │    │
│  │    but the complaint was filed Jan 20, 2026.       │    │
│  │    This 45-day gap is unusual for shipping damage. │    │
│  │                                                     │    │
│  │ 2. KNOWN FRAUD IMAGE                               │    │
│  │    This image is 89% similar to an image used in   │    │
│  │    3 previous fraudulent claims (CASE-12340,       │    │
│  │    CASE-11987, CASE-11654).                        │    │
│  │                                                     │    │
│  │ 3. SERIAL NUMBER MISMATCH                          │    │
│  │    Extracted serial: XPS-2025-ZZZ999               │    │
│  │    Expected serial: XPS-2026-ABC123                │    │
│  │    These do not match.                             │    │
│  │                                                     │    │
│  │ 4. RETURN HISTORY                                  │    │
│  │    Customer has returned 5 items in last 30 days   │    │
│  │    (avg customer: 0.3 returns/month)               │    │
│  │                                                     │    │
│  │ RECOMMENDATION: Deny claim, flag account           │    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  Reviewer Actions:                                           │
│  [Approve Anyway]  [Deny - Fraud]  [Request More Info]      │
│  [Escalate to Manager]  [Contact Customer]                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

### Flow 4: Return Shipping Process

```
┌─────────────────────────────────────────────────────────────┐
│  RETURN SHIPPING WORKFLOW                                    │
└─────────────────────────────────────────────────────────────┘

[Case Approved - Replacement or Refund Selected]
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: GENERATE RETURN LABEL                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  System automatically:                                       │
│  ✓ Generates prepaid shipping label                         │
│  ✓ Creates tracking number                                  │
│  ✓ Sends to customer email                                  │
│  ✓ Notifies warehouse of incoming return                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Return Label Generated                              │    │
│  │                                                     │    │
│  │ Carrier: FedEx Ground                              │    │
│  │ Tracking: 1234567890                               │    │
│  │ Return By: February 3, 2026 (14 days)             │    │
│  │                                                     │    │
│  │ [Download Label]  [Email Label]  [Print Label]     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: CUSTOMER SHIPS ITEM                                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Customer receives email:                                    │
│  ───────────────────────────────────────────────────────    │
│  Subject: Your return label for Order #12345                │
│                                                              │
│  Hi John,                                                   │
│                                                              │
│  Your return has been approved. Please follow these steps:  │
│                                                              │
│  1. Pack the item securely in original packaging if         │
│     possible                                                │
│  2. Attach the return label (see attachment)                │
│  3. Drop off at any FedEx location                          │
│                                                              │
│  Return deadline: February 3, 2026                          │
│                                                              │
│  Once we receive and inspect the item, your                 │
│  replacement will ship within 1-2 business days.            │
│  ───────────────────────────────────────────────────────    │
│                                                              │
│  Tracking updates sent via SMS and email                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: WAREHOUSE RECEIVES RETURN                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  When item arrives at warehouse:                            │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ WAREHOUSE INSPECTION CHECKLIST                      │    │
│  ├─────────────────────────────────────────────────────┤    │
│  │                                                     │    │
│  │ ☑ Scan return label barcode                        │    │
│  │ ☐ Verify serial number matches case                │    │
│  │ ☐ Photograph item condition                        │    │
│  │ ☐ Compare to original complaint photos             │    │
│  │ ☐ Grade condition: [A] [B] [C] [D] [Reject]       │    │
│  │                                                     │    │
│  │ Notes: ________________________________            │    │
│  │                                                     │    │
│  │ [Complete Inspection]                              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  CV-Assisted Inspection (Option 2/3):                       │
│  - Warehouse photo compared to complaint photo              │
│  - Auto-verify damage matches claim                         │
│  - Flag discrepancies for review                            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: PROCESS RESOLUTION                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  IF inspection passes:                                       │
│    → Ship replacement OR process refund                     │
│    → Notify customer via email/SMS                          │
│    → Close case                                             │
│                                                              │
│  IF inspection fails:                                        │
│    → Escalate to fraud review                               │
│    → Hold replacement/refund                                │
│    → Contact customer for clarification                     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ CUSTOMER NOTIFICATION                               │    │
│  │                                                     │    │
│  │ "Great news! We've received and inspected your     │    │
│  │  return. Your replacement is on its way!"          │    │
│  │                                                     │    │
│  │  New Tracking: 9876543210                          │    │
│  │  Estimated Delivery: January 25, 2026              │    │
│  │                                                     │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Fraud Detection Strategies

### Signal Categories

| Category | Signals | Detection Method |
|----------|---------|------------------|
| **Image Fraud** | Stock photos, edited images, reused photos | pHash, EXIF, reverse search |
| **Identity Fraud** | Fake accounts, stolen credentials | Account age, login patterns |
| **Return Abuse** | Serial returners, wardrobing | Return history analysis |
| **Product Fraud** | Wrong item, tampered serial | Serial verification, CV comparison |
| **Claim Fraud** | Exaggerated damage, non-existent damage | CV damage verification |

### Fraud Scoring Model

```python
class FraudScorer:
    """
    Weighted fraud scoring based on multiple signals.
    """

    WEIGHTS = {
        # Image signals
        "image_hash_match_fraud_db": 0.35,
        "exif_date_mismatch": 0.15,
        "stock_photo_detected": 0.25,
        "manipulation_detected": 0.20,

        # Customer signals
        "high_return_frequency": 0.15,
        "account_age_under_30_days": 0.10,
        "previous_fraud_flag": 0.30,
        "chargeback_history": 0.25,

        # Product signals
        "serial_mismatch": 0.40,
        "product_category_mismatch": 0.30,
        "damage_not_visible": 0.20,
    }

    def calculate_score(self, signals: dict) -> float:
        """
        Calculate fraud probability from 0-1.

        Args:
            signals: Dict of signal_name -> bool (detected or not)

        Returns:
            Fraud probability score
        """
        score = 0.0
        max_possible = 0.0

        for signal, detected in signals.items():
            weight = self.WEIGHTS.get(signal, 0.1)
            max_possible += weight
            if detected:
                score += weight

        # Normalize to 0-1 range
        return min(1.0, score / max_possible) if max_possible > 0 else 0.0

    def get_risk_level(self, score: float) -> str:
        """Map score to risk category."""
        if score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        elif score >= 0.2:
            return "low"
        return "minimal"
```

### Fraud Prevention Actions

| Risk Level | Auto Action | Human Action |
|------------|-------------|--------------|
| **Minimal** (<0.2) | Auto-approve if policy allows | None required |
| **Low** (0.2-0.4) | Auto-approve with monitoring | Review if high value |
| **Medium** (0.4-0.7) | Hold for review | Required review |
| **High** (>0.7) | Block auto-approval | Manager escalation |

---

## Refund & Return Shipping Workflows

### Refund Processing

```
┌─────────────────────────────────────────────────────────────┐
│  REFUND WORKFLOW                                             │
└─────────────────────────────────────────────────────────────┘

[Refund Approved]
      │
      ├── Is return required?
      │         │
      │    YES  │  NO (e.g., item under $50)
      │    │    │
      │    ▼    ▼
      │  [Wait for return]  [Process immediately]
      │         │                    │
      │         ▼                    │
      │  [Return received]           │
      │         │                    │
      │         ▼                    │
      │  [Inspect item]              │
      │         │                    │
      │    PASS │  FAIL              │
      │    │    │                    │
      │    ▼    ▼                    │
      │  [Refund] [Escalate]         │
      │    │         │               │
      │    └─────────┴───────────────┘
      │              │
      ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│  REFUND PROCESSING                                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Original Payment Method:                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Credit Card (**** 1234)                             │    │
│  │ Refund: $1,299.00                                   │    │
│  │ Processing: 5-7 business days                       │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  OR if original method unavailable:                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Store Credit                                        │    │
│  │ Amount: $1,299.00                                   │    │
│  │ Expires: January 20, 2027                          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Return Shipping Options

| Scenario | Who Pays | Method |
|----------|----------|--------|
| **Defective/Damaged (our fault)** | Company | Prepaid label sent |
| **Wrong item shipped** | Company | Prepaid label sent |
| **Customer changed mind** | Customer | Self-pay return |
| **Fraud suspected** | Hold | No label until review |

### Return Label Generation

```python
# src/app/services/shipping.py

class ShippingService:
    """Handles return label generation and tracking."""

    async def create_return_label(
        self,
        case_id: str,
        customer_address: Address,
        warehouse_address: Address,
        item_weight_lbs: float,
    ) -> ReturnLabel:
        """
        Generate prepaid return shipping label.
        """

        # Select carrier based on cost/speed
        carrier = self._select_carrier(
            origin=customer_address,
            weight=item_weight_lbs
        )

        # Create shipment with carrier API
        shipment = await carrier.create_shipment(
            from_address=customer_address,
            to_address=warehouse_address,
            weight=item_weight_lbs,
            service="ground",  # Cost-effective for returns
        )

        # Store in database
        label = ReturnLabel(
            case_id=case_id,
            carrier=carrier.name,
            tracking_number=shipment.tracking_number,
            label_url=shipment.label_url,
            expires_at=datetime.utcnow() + timedelta(days=14),
        )

        await self.db.save(label)

        # Send to customer
        await self.email_service.send_return_label(
            case_id=case_id,
            label_url=label.label_url,
            tracking_number=label.tracking_number,
        )

        return label
```

---

## Customer History Integration

### Logged-In User Data

```python
class CustomerContext:
    """
    Enrich complaint with customer history.
    """

    async def get_context(self, customer_id: str) -> dict:
        """
        Pull customer history for complaint enrichment.
        """

        customer = await self.db.get_customer(customer_id)

        return {
            # Identity
            "customer_id": customer.id,
            "account_age_days": (datetime.utcnow() - customer.created_at).days,
            "loyalty_tier": customer.tier,  # bronze, silver, gold, platinum
            "verified_email": customer.email_verified,
            "verified_phone": customer.phone_verified,

            # Purchase history
            "total_orders": await self.db.count_orders(customer_id),
            "total_spend": await self.db.sum_order_value(customer_id),
            "avg_order_value": await self.db.avg_order_value(customer_id),

            # Return history
            "total_returns": await self.db.count_returns(customer_id),
            "return_rate": await self.db.calculate_return_rate(customer_id),
            "returns_last_30_days": await self.db.count_recent_returns(customer_id, 30),

            # Support history
            "total_complaints": await self.db.count_complaints(customer_id),
            "open_cases": await self.db.count_open_cases(customer_id),
            "fraud_flags": await self.db.count_fraud_flags(customer_id),

            # Trust score (calculated)
            "trust_score": self._calculate_trust_score(customer),
        }

    def _calculate_trust_score(self, customer) -> float:
        """
        Calculate customer trustworthiness score.

        Higher score = more trusted = faster approvals
        """
        score = 0.5  # Base score

        # Positive signals
        if customer.account_age_days > 365:
            score += 0.1
        if customer.tier in ["gold", "platinum"]:
            score += 0.15
        if customer.total_orders > 10:
            score += 0.1
        if customer.email_verified and customer.phone_verified:
            score += 0.05

        # Negative signals
        if customer.return_rate > 0.3:  # >30% return rate
            score -= 0.2
        if customer.fraud_flags > 0:
            score -= 0.3
        if customer.returns_last_30_days > 3:
            score -= 0.15

        return max(0.0, min(1.0, score))
```

### Guest User Data

```python
class GuestContext:
    """
    Limited context for guest/receipt-only users.
    """

    async def get_context(self, order_id: str, receipt_data: dict) -> dict:
        """
        Pull what we know from the order/receipt.
        """

        order = await self.db.get_order(order_id)

        if not order:
            return {
                "status": "order_not_found",
                "trust_score": 0.3,  # Low trust for unverified
            }

        return {
            # Identity
            "customer_type": "guest",
            "email": receipt_data.get("email"),  # If provided
            "verified": False,

            # Order data
            "order_id": order.id,
            "order_date": order.created_at,
            "order_value": order.total_cents / 100,
            "items": [item.sku for item in order.items],

            # Verification
            "receipt_matched": self._verify_receipt(order, receipt_data),
            "within_return_window": self._check_return_window(order),

            # Trust score (lower for guests)
            "trust_score": 0.4 if self._verify_receipt(order, receipt_data) else 0.2,
        }
```

### Trust-Based Routing

| Trust Score | Auto-Approve Threshold | Review Required |
|-------------|----------------------|-----------------|
| **0.8-1.0** (Platinum) | Up to $500 | >$500 only |
| **0.6-0.8** (Gold) | Up to $200 | >$200 only |
| **0.4-0.6** (Standard) | Up to $50 | >$50 only |
| **0.2-0.4** (Low trust) | None | All cases |
| **<0.2** (Flagged) | None | Manager review |

---

## NLP Agent Notification Integration

### Email/SMS Notification Flow

```
┌─────────────────────────────────────────────────────────────┐
│  NLP AGENT NOTIFICATION SYSTEM                               │
└─────────────────────────────────────────────────────────────┘

[Case Status Changes]
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  NOTIFICATION ORCHESTRATOR                                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Triggers:                                                   │
│  - Case created                                             │
│  - Case status changed                                      │
│  - Return label generated                                   │
│  - Return received                                          │
│  - Refund processed                                         │
│  - Replacement shipped                                      │
│  - Human agent assigned                                     │
│  - Additional info needed                                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  NLP MESSAGE GENERATOR                                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Input:                                                      │
│  - Event type: "replacement_shipped"                        │
│  - Case context: {order_id, product, tracking_number}       │
│  - Customer preferences: {channel: "sms", language: "en"}   │
│  - CV analysis summary (if applicable)                      │
│                                                              │
│  Output (SMS):                                               │
│  "Your replacement Dell XPS 15 has shipped! Track it:       │
│   fedex.com/track?num=1234567890. Expected delivery:        │
│   Jan 25. Reply HELP for assistance."                       │
│                                                              │
│  Output (Email):                                             │
│  [Full HTML email with tracking link, timeline, etc.]       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  CHANNEL ROUTER                                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Customer Preferences:                                       │
│  ☑ Email (always)                                           │
│  ☑ SMS (opt-in)                                             │
│  ☐ Push notification (if app installed)                     │
│                                                              │
│  Message sent via:                                           │
│  - Email: SendGrid/SES                                      │
│  - SMS: Twilio                                              │
│  - Push: Firebase                                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Notification Templates

```python
# src/app/services/notifications.py

class NotificationService:
    """
    Generate and send customer notifications.
    Integrates CV analysis summary into messages.
    """

    TEMPLATES = {
        "case_created": {
            "email_subject": "We've received your case #{case_id}",
            "sms": "Case #{case_id} received. We'll review within 24hrs. Track: {track_url}",
        },
        "analysis_complete": {
            "email_subject": "Update on your case #{case_id}",
            "sms": "Case #{case_id} update: {ai_summary}. Next step: {next_action}",
        },
        "return_label_ready": {
            "email_subject": "Your return label is ready - Case #{case_id}",
            "sms": "Return label ready for case #{case_id}. Check email or: {label_url}",
        },
        "return_received": {
            "email_subject": "We've received your return - Case #{case_id}",
            "sms": "Return received! Processing your {resolution_type}. Updates coming soon.",
        },
        "refund_processed": {
            "email_subject": "Your refund has been processed - Case #{case_id}",
            "sms": "Refund of {amount} processed to {payment_method}. Allow 5-7 days.",
        },
        "replacement_shipped": {
            "email_subject": "Your replacement is on its way! - Case #{case_id}",
            "sms": "Replacement shipped! Track: {tracking_url}. Est. delivery: {eta}",
        },
        "human_assigned": {
            "email_subject": "An agent is reviewing your case #{case_id}",
            "sms": "Agent {agent_name} is reviewing case #{case_id}. Expect update within {sla}.",
        },
        "info_needed": {
            "email_subject": "Action needed: Additional info for case #{case_id}",
            "sms": "We need more info for case #{case_id}. Please reply or visit: {action_url}",
        },
    }

    async def send_notification(
        self,
        event: str,
        case: Case,
        cv_analysis: dict = None,
        channels: list = ["email", "sms"],
    ):
        """
        Send notification with optional CV analysis summary.
        """

        template = self.TEMPLATES.get(event)
        if not template:
            return

        # Build context
        context = {
            "case_id": case.id,
            "customer_name": case.customer_name,
            "product": case.product_name,
            "amount": f"${case.refund_amount / 100:.2f}" if case.refund_amount else None,
            "tracking_url": case.tracking_url,
            "label_url": case.return_label_url,
            "eta": case.estimated_delivery,
            "track_url": f"https://shop.example.com/cases/{case.id}",
            "action_url": f"https://shop.example.com/cases/{case.id}/respond",
        }

        # Add CV summary if available
        if cv_analysis:
            context["ai_summary"] = self._build_ai_summary(cv_analysis)
            context["next_action"] = cv_analysis.get("suggested_action", "Review in progress")

        # Send via each channel
        for channel in channels:
            if channel == "email" and case.customer_email:
                await self._send_email(
                    to=case.customer_email,
                    subject=template["email_subject"].format(**context),
                    body=self._render_email_template(event, context),
                )

            elif channel == "sms" and case.customer_phone and case.sms_opt_in:
                await self._send_sms(
                    to=case.customer_phone,
                    body=template["sms"].format(**context),
                )

    def _build_ai_summary(self, cv_analysis: dict) -> str:
        """
        Build human-readable summary from CV analysis.
        """
        damage_type = cv_analysis.get("damage_type", "issue")
        severity = cv_analysis.get("severity", "")
        confidence = cv_analysis.get("confidence", 0)

        if confidence > 0.8:
            return f"We've identified {severity} {damage_type} in your photos"
        else:
            return f"We're reviewing the {damage_type} you reported"
```

---

## Disclaimers & User Messaging

### Disclaimer Text Options

#### Option 1: Transparent & Friendly

```
┌─────────────────────────────────────────────────────────────┐
│  ℹ️ AI-Assisted Analysis                                     │
│                                                              │
│  Our AI assistant has provided a preliminary assessment     │
│  based on your photos. A member of our team will verify     │
│  the details before any action is taken.                    │
│                                                              │
│  What the AI detected:                                       │
│  • Damage type: Screen crack                                │
│  • Severity: Major                                          │
│  • Confidence: High                                         │
│                                                              │
│  This analysis helps us route your case to the right        │
│  team faster.                                               │
└─────────────────────────────────────────────────────────────┘
```

#### Option 2: Minimal & Professional

```
┌─────────────────────────────────────────────────────────────┐
│  Automated analysis complete.                                │
│                                                              │
│  Your photos have been analyzed to help expedite your       │
│  case. All claims are subject to verification.              │
└─────────────────────────────────────────────────────────────┘
```

#### Option 3: Detailed & Technical

```
┌─────────────────────────────────────────────────────────────┐
│  🤖 AI Analysis Results                                      │
│                                                              │
│  Analysis Type: Computer Vision (Damage Detection)          │
│  Model Version: v1.2.3                                      │
│  Confidence Level: 87%                                      │
│                                                              │
│  Findings:                                                   │
│  ├─ Primary: Physical damage (screen)                       │
│  ├─ Severity: Major                                         │
│  └─ Serial: Extracted (XPS-2026-ABC123)                     │
│                                                              │
│  Note: This is an automated preliminary assessment.         │
│  Final determination will be made by our support team.      │
│  Analysis accuracy may vary based on image quality.         │
└─────────────────────────────────────────────────────────────┘
```

### When to Show Disclaimers

| Scenario | Disclaimer Level | Why |
|----------|------------------|-----|
| **High confidence (>85%)** | Minimal | Don't over-warn when accurate |
| **Medium confidence (60-85%)** | Friendly | Set expectations |
| **Low confidence (<60%)** | Detailed | Explain limitations |
| **Auto-approved** | None shown | Seamless experience |
| **Escalated to human** | Professional | They'll get human anyway |

### Legal/Compliance Language

```python
DISCLAIMERS = {
    "preliminary": (
        "This is a preliminary AI-assisted assessment. "
        "Final decisions are made by our support team."
    ),
    "assisted": (
        "AI analysis helps route your case faster. "
        "All resolutions are verified by our team."
    ),
    "beta": (
        "You're using our new AI-assisted support (beta). "
        "We appreciate your patience as we improve the system."
    ),
    "privacy": (
        "Your images are analyzed to process your claim and are "
        "retained according to our privacy policy."
    ),
}
```

---

## Technical Implementation

### Database Schema Additions

```sql
-- Add to existing schema for CV complaint triage

-- CV analysis results
CREATE TABLE cv_analyses (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    image_url TEXT NOT NULL,

    -- Classification results
    damage_type TEXT,
    damage_location TEXT,
    severity TEXT,
    confidence REAL,

    -- Fraud signals
    fraud_risk TEXT,
    fraud_signals JSONB,
    trust_score REAL,

    -- Extracted data
    serial_number TEXT,
    extracted_text TEXT,
    raw_labels JSONB,

    -- Metadata
    model_version TEXT,
    processing_time_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now')),

    -- For Option 2/3: perceptual hash for fraud detection
    image_phash TEXT
);

CREATE INDEX idx_cv_analyses_case ON cv_analyses(case_id);
CREATE INDEX idx_cv_analyses_phash ON cv_analyses(image_phash);

-- Customer trust scores (cached)
CREATE TABLE customer_trust_scores (
    customer_id TEXT PRIMARY KEY,
    trust_score REAL NOT NULL,

    -- Component scores
    account_age_score REAL,
    purchase_history_score REAL,
    return_history_score REAL,
    fraud_history_score REAL,

    -- Metadata
    calculated_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT
);

-- Fraud image hash database
CREATE TABLE fraud_image_hashes (
    phash TEXT PRIMARY KEY,
    first_seen_case_id TEXT,
    times_seen INTEGER DEFAULT 1,
    confirmed_fraud BOOLEAN DEFAULT FALSE,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Return labels
CREATE TABLE return_labels (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),

    carrier TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    label_url TEXT NOT NULL,

    status TEXT DEFAULT 'generated',  -- generated, shipped, delivered, expired

    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    shipped_at TEXT,
    delivered_at TEXT
);
```

### API Endpoints

```python
# src/app/routers/complaints.py

from fastapi import APIRouter, UploadFile, File, Depends
from typing import List, Optional

router = APIRouter(prefix="/api/v1/complaints", tags=["complaints"])


@router.post("/submit")
async def submit_complaint(
    order_id: str,
    issue_type: str,
    description: str,
    images: List[UploadFile] = File(default=[]),
    customer: Customer = Depends(get_current_customer_or_guest),
):
    """
    Submit a new complaint with optional images.
    Returns case ID and preliminary AI analysis.
    """
    pass


@router.post("/submit-guest")
async def submit_complaint_guest(
    receipt_image: UploadFile = File(...),
    issue_type: str,
    description: str,
    damage_images: List[UploadFile] = File(default=[]),
    email: str,
    phone: Optional[str] = None,
):
    """
    Submit complaint as guest using receipt verification.
    """
    pass


@router.get("/{case_id}/status")
async def get_case_status(
    case_id: str,
    customer: Customer = Depends(get_current_customer_or_guest),
):
    """
    Get current status and AI analysis of a case.
    """
    pass


@router.post("/{case_id}/add-images")
async def add_images_to_case(
    case_id: str,
    images: List[UploadFile] = File(...),
    customer: Customer = Depends(get_current_customer_or_guest),
):
    """
    Add additional images to an existing case.
    Triggers re-analysis.
    """
    pass


@router.get("/{case_id}/return-label")
async def get_return_label(
    case_id: str,
    customer: Customer = Depends(get_current_customer_or_guest),
):
    """
    Get return shipping label for approved case.
    """
    pass


@router.post("/{case_id}/select-resolution")
async def select_resolution(
    case_id: str,
    resolution: str,  # "replacement", "refund", "store_credit"
    customer: Customer = Depends(get_current_customer_or_guest),
):
    """
    Customer selects their preferred resolution.
    """
    pass
```

---

## Comparison Matrix

| Feature | Option 1 | Option 2 | Option 3 |
|---------|----------|----------|----------|
| **Time to ship** | 1-2 weeks | 3-4 weeks | 6-8 weeks |
| **Monthly cost** | $50-200 | $100-400 | $300-800 |
| **Training data needed** | 0 images | 500+ images | 1000+ images |
| **Damage classification** | 70-75% | 85-92% | 90-95% |
| **Custom categories** | ❌ No | ✅ Yes | ✅ Yes |
| **Severity grading** | Basic | Good | Excellent |
| **OCR (serial numbers)** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Fraud: EXIF check** | ❌ No | ✅ Yes | ✅ Yes |
| **Fraud: Hash DB** | ❌ No | ✅ Basic | ✅ Advanced |
| **Fraud: Stock photo** | ❌ No | ⚠️ Basic | ✅ Reverse search |
| **Fraud: Manipulation** | ❌ No | ⚠️ Basic | ✅ Forensics |
| **Product verification** | ❌ No | ❌ No | ✅ Embedding match |
| **Customer history** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Trust scoring** | Basic | Moderate | Advanced |
| **Auto-approval** | ⚠️ Limited | ✅ Moderate | ✅ Comprehensive |
| **Human enrichment** | Basic | Good | Excellent |
| **Recommended for** | MVP launch | Growth | Enterprise |

---

## Recommended Path

### Start with Option 1 (Ship Fast)

1. **Week 1**: Integrate Google Vision API (labels + OCR)
2. **Week 2**: Build label mapping rules + basic routing
3. **Week 3**: Add customer history integration
4. **Week 4**: Deploy with disclaimers, collect feedback

### Upgrade to Option 2 (After 1000+ Complaints)

1. Use collected images to train custom classifier
2. Add EXIF checking and basic fraud signals
3. Implement perceptual hashing for repeat image detection
4. Tune confidence thresholds based on real data

### Evolve to Option 3 (When Fraud Becomes a Problem)

1. Add reverse image search integration
2. Build sophisticated fraud scoring model
3. Implement product verification via embeddings
4. Add image forensics for manipulation detection

---

## Summary

**Your idea is solid and practical.** You're not overcomplicating things - you're building exactly what successful e-commerce companies use.

**Key insight**: Start with Option 1, ship fast, collect data, then iterate. The biggest mistake would be building Option 3 before you have the data to train it properly.

**Data to start collecting now** (even before CV is live):
- All complaint images (store them!)
- Manual classifications by support agents
- Resolution outcomes (approved/denied/fraud)
- Customer feedback on AI accuracy

This becomes your training dataset for Option 2.

---

*Document generated for ShopSquire MVP planning. Update as implementation progresses.*
