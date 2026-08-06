"""Typed turn envelope + unified core response (V2 Phase 4, step 1).

TWO types replace the payload-dict soup that made suggest() unownable:
  • TurnEnvelope  — everything a turn needs, typed, tenant-scoped, built ONCE at the edge.
  • CoreResponse  — the ONE internal response shape. The four recorded /suggest contract
    forks (full_pipeline / inventory_fast / claims / policy_faq) exist ONLY in
    legacy_adapter.to_legacy() — internal code never branches on output shape again.

Money is CENTS internally (the read-model's unit); the legacy edge speaks dollars — the
conversion happens exactly once, in from_suggest_params / the adapter. Every response is
traceable (trace_id/decision_id — the 4 UNIVERSAL contract fields) and carries its
grounding status so degradation is explicit, never implied.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = logging.getLogger("shopsquire.recommendation_core.envelope")

LANES = ("SEARCH", "FILTER", "COMPARE", "EXPLAIN", "SUPPORT_CLAIM", "CART_MUTATE",
         "PROCUREMENT", "OFF_CATALOG", "POLICY_QUESTION", "INVENTORY")


@dataclass(frozen=True)
class ImageObservation:
    """Bounded, policy-filtered facts derived from an upload.

    Vision identifies facts; the shared core remains the only owner of taxonomy selection,
    retrieval, constraints and rank. Raw pixels and OCR payloads never enter this envelope.
    """
    labels: tuple[str, ...] = ()
    product_identity: Dict[str, str] = field(default_factory=dict)
    image_hash: Optional[str] = None
    analysis_state: str = "pending"       # complete | pending | degraded
    trust_mode: str = "text_only"         # full | sanitized | text_only

    @classmethod
    def bounded(cls, *, labels: Optional[List[Any]] = None,
                product_identity: Optional[Dict[str, Any]] = None,
                image_hash: Optional[str] = None, analysis_state: str = "pending",
                trust_mode: str = "text_only") -> "ImageObservation":
        safe_labels = tuple(str(value).strip()[:80] for value in (labels or [])[:12]
                            if str(value).strip())
        safe_identity: Dict[str, str] = {}
        for key in ("brand", "product_type", "category", "model", "family", "form_factor"):
            value = (product_identity or {}).get(key)
            if value is not None and str(value).strip():
                safe_identity[key] = str(value).strip()[:120]
        state = analysis_state if analysis_state in ("complete", "pending", "degraded") else "pending"
        trust = trust_mode if trust_mode in ("full", "sanitized", "text_only") else "text_only"
        if trust == "text_only":
            safe_labels, safe_identity = (), {}
        elif trust == "sanitized":
            safe_identity = {}
        return cls(labels=safe_labels, product_identity=safe_identity,
                   image_hash=(str(image_hash)[:128] if image_hash else None),
                   analysis_state=state, trust_mode=trust)

    def to_dict(self) -> Dict[str, Any]:
        return {"labels": list(self.labels), "product_identity": dict(self.product_identity),
                "image_hash": self.image_hash, "analysis_state": self.analysis_state,
                "trust_mode": self.trust_mode}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ImageObservation":
        return cls.bounded(labels=list(value.get("labels") or []),
                           product_identity=dict(value.get("product_identity") or {}),
                           image_hash=value.get("image_hash"),
                           analysis_state=str(value.get("analysis_state") or "pending"),
                           trust_mode=str(value.get("trust_mode") or "text_only"))


@dataclass(frozen=True)
class TurnEnvelope:
    """One turn's typed input. Frozen: stages derive, they never mutate the request."""
    tenant_id: str
    uid: str
    query: str
    trace_id: str
    # Authoritative settlement currency for this tenant/store. Products in another currency
    # are not comparable until a bounded FX quote is attached at ingress.
    currency: str = "USD"
    # A bounded classification supplied by the API edge. It is advisory for fresh turns; the
    # router may use it to preserve an EXPLAIN/COMPARE continuation only when session evidence
    # proves there is an existing shortlist to discuss.
    intent_hint: Optional[str] = None
    budget_min_cents: Optional[int] = None
    budget_max_cents: Optional[int] = None
    has_image: bool = False
    image_observations: List[ImageObservation] = field(default_factory=list)
    source_ip: Optional[str] = None
    external_research_consent: bool = False
    # Buyer-authored response to the active material question. It may refine an
    # evidence query, but it is never itself an authoritative product requirement.
    clarification_answer: Dict[str, Any] = field(default_factory=dict)
    session: Dict[str, Any] = field(default_factory=dict)   # prior shortlist/slots (read-only)
    # cart: the CURRENT cart lines [{sku,name,quantity}], read once at the facade ingress. The
    # cart-mutation resolver binds the shopper's named targets ('the ThinkPad') to a REAL line
    # by SKU — the model never invents a SKU. Empty on the no-cart path (search-only turns /
    # offline replay). Read-only here; execution is the caller's job (plan, then act).
    cart: List[Dict[str, Any]] = field(default_factory=list)
    # pre_gate: the SHARED commerce guard's verdict, run once at the facade ingress and passed
    # in — so the core reads the REAL guard (inspect_commerce_request) instead of its own
    # regex. None only on the no-facade path (offline replay / direct tests), where the core
    # falls back to its thin gate. Shape: {"policy_route","verdict","reasons",...}.
    pre_gate: Optional[Dict[str, Any]] = None

    @classmethod
    def from_suggest_params(cls, *, query: str, uid: str = "", tenant_id: str = "default",
                            budget_min: Optional[float] = None, budget_max: Optional[float] = None,
                            currency: Optional[str] = None,
                            trace_id: Optional[str] = None, has_image: bool = False,
                            image_observations: Optional[List[ImageObservation]] = None,
                            source_ip: Optional[str] = None,
                            external_research_consent: bool = False,
                            clarification_answer: Optional[Dict[str, Any]] = None,
                            intent_hint: Optional[str] = None,
                            session: Optional[Dict[str, Any]] = None,
                            cart: Optional[List[Dict[str, Any]]] = None,
                            pre_gate: Optional[Dict[str, Any]] = None) -> "TurnEnvelope":
        """The /suggest edge speaks DOLLARS; internal is CENTS — converted here, once."""
        to_cents = lambda v: int(round(float(v) * 100)) if v is not None else None  # noqa: E731
        # Legacy suggest() historically parsed free-text budgets after V2 dispatch. Normalize
        # the shared grammar here so the core does not depend on order inside that monolith.
        if budget_min is None and budget_max is None:
            try:
                from src.app.services.budget_grammar import parse_budget
                parsed = parse_budget(query)
                if parsed is not None:
                    budget_min, budget_max = parsed.budget_min, parsed.budget_max
            except Exception as exc:
                # Input normalization is best-effort; no budget remains an honest core state.
                logger.debug(
                    "Budget grammar normalization skipped: %s",
                    repr(exc)[:120],
                )
        normalized_hint = str(intent_hint or "").strip().upper()
        if normalized_hint not in LANES:
            normalized_hint = None
        if currency is None:
            try:
                from src.app.platform.store_profile import profile_slot
                currency = profile_slot("currency", default="USD")
            except Exception:
                currency = "USD"
        normalized_currency = str(currency or "USD").strip().upper()
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            normalized_currency = "USD"
        return cls(tenant_id=str(tenant_id or "default"), uid=str(uid or ""),
                   query=str(query or "").strip(), trace_id=trace_id or str(uuid.uuid4()),
                   currency=normalized_currency,
                   intent_hint=normalized_hint,
                   budget_min_cents=to_cents(budget_min), budget_max_cents=to_cents(budget_max),
                   has_image=bool(has_image or image_observations),
                   image_observations=list(image_observations or []), source_ip=source_ip,
                   external_research_consent=bool(external_research_consent),
                   clarification_answer=dict(clarification_answer or {}),
                   session=dict(session or {}),
                   cart=list(cart or []), pre_gate=pre_gate)

    def to_dict(self) -> Dict[str, Any]:
        """Wire form for shadow jobs (R10.1/P1.1) — CENTS-exact, every field the core reads.
        A shadow job that drops budget/session/image measures a DIFFERENT turn than production
        served; this is the full-fidelity round-trip that closes that gap."""
        return {"tenant_id": self.tenant_id, "uid": self.uid, "query": self.query,
                "trace_id": self.trace_id, "currency": self.currency,
                "intent_hint": self.intent_hint,
                "budget_min_cents": self.budget_min_cents,
                "budget_max_cents": self.budget_max_cents, "has_image": self.has_image,
                "image_observations": [item.to_dict() for item in self.image_observations],
                "source_ip": self.source_ip,
                "external_research_consent": self.external_research_consent,
                "clarification_answer": dict(self.clarification_answer),
                "session": dict(self.session),
                "cart": list(self.cart), "pre_gate": self.pre_gate}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TurnEnvelope":
        """Inverse of to_dict — cents stay cents (never re-converted), unknown keys ignored."""
        _int = lambda v: int(v) if v is not None else None  # noqa: E731
        hint = str(d.get("intent_hint") or "").strip().upper()
        if hint not in LANES:
            hint = None
        return cls(tenant_id=str(d.get("tenant_id") or "default"), uid=str(d.get("uid") or ""),
                   query=str(d.get("query") or ""), trace_id=str(d.get("trace_id") or uuid.uuid4()),
                   currency=(str(d.get("currency") or "USD").strip().upper()
                             if len(str(d.get("currency") or "USD").strip()) == 3 else "USD"),
                   intent_hint=hint,
                   budget_min_cents=_int(d.get("budget_min_cents")),
                   budget_max_cents=_int(d.get("budget_max_cents")),
                   has_image=bool(d.get("has_image") or d.get("image_observations")),
                   image_observations=[ImageObservation.from_dict(item) for item in
                                       (d.get("image_observations") or []) if isinstance(item, dict)],
                   source_ip=d.get("source_ip"),
                   external_research_consent=bool(d.get("external_research_consent")),
                   clarification_answer=dict(d.get("clarification_answer") or {}),
                   session=dict(d.get("session") or {}), cart=list(d.get("cart") or []),
                   pre_gate=d.get("pre_gate"))


@dataclass
class ProductCard:
    """One recommended item — a projection of catalog_read_model.VariantView plus verdicts."""
    sku: str
    title: str = ""
    price_cents: Optional[int] = None
    currency: str = "USD"
    brand: str = ""
    image_url: str = ""
    stock: Optional[int] = None
    stock_source: Optional[str] = None
    why: List[str] = field(default_factory=list)
    fit: Optional[Dict[str, Any]] = None      # attribute_registry.evaluate_requirements output

    def as_dict(self) -> Dict[str, Any]:
        return {"sku": self.sku, "name": self.title, "price": (self.price_cents or 0) / 100.0,
                "price_cents": self.price_cents, "currency": self.currency, "brand": self.brand,
                "image_url": self.image_url, "stock": self.stock, "why": list(self.why),
                "workload_fit": self.fit}


class MsgPriority:
    """Explicit priority ladder for the primary buyer message (V2 review-10 P0.5). Replaces the
    old execution-order-wins mutation: a stage states WHERE its prose sits in the hierarchy, not
    when it happens to run, so inserting or reordering a stage can no longer silently change which
    sentence the buyer reads. Higher wins; ties go to the later caller (matches the previous
    last-writer-wins within a tier). Values mirror the behaviour the sequential mutation produced."""
    CAPABILITY_WITHIN_BUDGET = 5    # guarded fill-only confirm — loses to any lane-base message
    LANE_BASE = 10                  # a lane executor's base prose (search/filter/explain/compare/…)
    CAPABILITY_STATEMENT = 20       # floor-stated / below-budget tradeoff — overrides lane base
    BULK_VERDICT = 50               # bulk fits / over-budget menu
    BULK_SCOPE_CLARIFY = 60         # per-unit-vs-total ambiguity — must be asked before anything
    REFUSAL = 100                   # off-catalog honesty (composed refusal-aware prose)


@dataclass
class StageResult:
    """One core stage's typed outcome (V2 review-10 P0.5). Carries the operational breadcrumb the
    canary needs — status / latency / retrieval count — so per-stage cost is measurable instead of
    hidden inside a monolithic turn. The message it may have claimed lives on CoreResponse.message
    (via set_message); this record is telemetry, never the source of the prose."""
    stage: str
    status: str = "ok"              # ok | clarify | conflict | skipped | error
    latency_ms: float = 0.0
    retrieval_count: int = 0
    won_message: bool = False       # did this stage claim the primary-message slot?
    data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"stage": self.stage, "status": self.status,
                "latency_ms": round(self.latency_ms, 1),
                "retrieval_count": self.retrieval_count, "won_message": self.won_message,
                **({"data": self.data} if self.data else {})}


@dataclass
class CoreResponse:
    """THE unified response. Invariants (enforced by finalize()):
      • message is NEVER empty — the recovery-answer guarantee (kills the valorant
        silent-zero known_wrong at the type level, not as a patch).
      • off_catalog and non-empty products are mutually exclusive (honesty).
      • grounding != 'grounded' must be visible (degraded flows from it)."""
    envelope: TurnEnvelope
    lane: str = "SEARCH"
    message: str = ""
    products: List[ProductCard] = field(default_factory=list)
    off_catalog: Optional[Dict[str, Any]] = None       # {class,label,supplier_rfq_offer}
    refusal_note: Optional[str] = None
    clarify: List[Dict[str, Any]] = field(default_factory=list)
    fit_summary: Optional[Dict[str, Any]] = None       # floors + per-product verdict counts
    grounding: str = "grounded"                         # taxonomy_registry.grounding_status
    degraded: bool = False
    decision_id: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)  # stage breadcrumbs for the adapter
    stage_results: List[StageResult] = field(default_factory=list)  # P0.5 per-stage telemetry
    # highest message priority claimed so far (P0.5). -1 = unclaimed; not a constructor concern.
    _msg_priority: int = field(default=-1, repr=False)

    def set_message(self, text: str, priority: int) -> bool:
        """Claim the primary-message slot IFF priority >= the highest claimed so far. This is the
        composer: a stage declares its priority (MsgPriority.*), never relies on running last. An
        empty/blank text never claims. Returns True if it won the slot (so a stage can record it)."""
        if not str(text or "").strip():
            return False
        if priority >= self._msg_priority:
            self.message = text
            self._msg_priority = priority
            return True
        return False

    def record_stage(self, stage: str, *, status: str = "ok", latency_ms: float = 0.0,
                     retrieval_count: int = 0, won_message: bool = False,
                     **data: Any) -> None:
        """Append one stage's operational breadcrumb. Additive — never touches the message."""
        self.stage_results.append(StageResult(
            stage=stage, status=status, latency_ms=latency_ms, retrieval_count=retrieval_count,
            won_message=won_message, data=dict(data)))

    def finalize(self) -> "CoreResponse":
        """Enforce the invariants; called once by the orchestrator before the adapter."""
        if not self.decision_id:
            self.decision_id = self.envelope.trace_id
        if self.stage_results:
            self.extras["stage_results"] = [s.as_dict() for s in self.stage_results]
        if self.off_catalog:
            self.products = []
            # a message composed BEFORE the refusal decision ("Here are 2 options.") must not
            # survive it — regenerate unless a stage explicitly composed refusal-aware prose
            if not self.extras.get("refusal_message_composed"):
                self.message = ""
                self._msg_priority = -1
        if self.grounding == "error":
            self.degraded = True
        if not str(self.message or "").strip():
            self.message = self._recovery_message()
        return self

    def _recovery_message(self) -> str:
        """Deterministic never-empty floor. A model-grounded explanation normally overwrites
        this; its absence must still leave the buyer with an honest, actionable sentence."""
        if self.off_catalog:
            label = str(self.off_catalog.get("label") or "that category")
            return (f"Honest answer: we don't stock {label}. I can raise a supplier request "
                    f"for a quote if you'd like us to source it.")
        if self.refusal_note:
            return self.refusal_note
        if self.products:
            return f"I found {len(self.products)} options that match your request."
        if self.clarify:
            return "I need one detail to get this right — see the question below."
        if self.degraded:
            return ("I couldn't verify our catalog just now, so I won't guess. "
                    "Please try again in a moment.")
        return ("No exact match in our catalog for that. The closest alternatives are shown "
                "when available — or tell me what to relax (budget, brand, specs).")
