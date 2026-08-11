from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import TIMESTAMP, JSON, Boolean, Integer, Text, ForeignKey, UniqueConstraint
import uuid


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    sku: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, default="USD")
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    specs: Mapped[dict | None] = mapped_column(JSON, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class ProductConfiguration(Base):
    """Exact sellable configuration; additive to the legacy product projection."""

    __tablename__ = "product_configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", "configuration_hash", name="uq_product_configuration"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(Text, default="default")
    product_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("products.id", ondelete="SET NULL"), nullable=True,
    )
    sku: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text, nullable=True)
    mpn: Mapped[str | None] = mapped_column(Text, nullable=True)
    retailer_sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    retailer: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration_hash: Mapped[str] = mapped_column(Text)
    form_factor: Mapped[str] = mapped_column(Text, default="unknown")
    mobility: Mapped[str] = mapped_column(Text, default="unknown")
    device_class: Mapped[str] = mapped_column(Text, default="unknown")
    os_edition: Mapped[str | None] = mapped_column(Text, nullable=True)
    gpu_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    gpu_vram_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_tgp_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_installed_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_ceiling_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_upgradeable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    storage_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warranty_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    warranty_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, default="AUD")
    specification_observed_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    price_observed_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    availability_observed_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductEvidenceObservation(Base):
    """One provenance-bearing fact. Conflicting facts are retained as separate rows."""

    __tablename__ = "product_evidence_observations"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    configuration_id: Mapped[str] = mapped_column(
        Text, ForeignKey("product_configurations.id", ondelete="CASCADE"),
    )
    attribute_key: Mapped[str] = mapped_column(Text)
    value_json: Mapped[dict] = mapped_column(JSON)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_class: Mapped[str] = mapped_column(Text)
    evidence_status: Mapped[str] = mapped_column(Text, default="observed")
    conflict_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str] = mapped_column(Text)
    source_record_id: Mapped[str] = mapped_column(Text)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[str] = mapped_column(TIMESTAMP)
    expires_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("product_evidence_observations.id"), nullable=True,
    )


class ProductAvailabilityObservation(Base):
    __tablename__ = "product_availability_observations"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    configuration_id: Mapped[str] = mapped_column(
        Text, ForeignKey("product_configurations.id", ondelete="CASCADE"),
    )
    location_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_min_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_max_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_record_id: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[str] = mapped_column(TIMESTAMP)
    expires_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class ShoppingCase(Base):
    __tablename__ = "shopping_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", name="uq_shopping_case_tenant"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[str] = mapped_column(Text, default="default")
    uid: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    retained_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class RequirementProposal(Base):
    __tablename__ = "requirement_proposals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "proposal_id", name="uq_requirement_proposal_tenant"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    proposal_id: Mapped[str] = mapped_column(Text)
    case_id: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[str] = mapped_column(Text, default="default")
    uid: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(Text, default="pending_review")
    source_reference: Mapped[str] = mapped_column(Text)
    claims_json: Mapped[list] = mapped_column(JSON)
    acceptance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acceptance_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class ShoppingCasePublisherCandidate(Base):
    """A discovered origin whose authority is bounded to one shopping case."""

    __tablename__ = "shopping_case_publisher_candidates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", "url", name="uq_case_publisher_candidate_url"),
    )

    candidate_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text)
    case_id: Mapped[str] = mapped_column(Text)
    uid: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    query_axes_json: Mapped[list] = mapped_column(JSON, default=list)
    discovery_receipt_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(Text, default="discovered")
    authority_status: Mapped[str] = mapped_column(Text, default="not_accepted")
    approval_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_claim_types_json: Mapped[list] = mapped_column(JSON, default=list)
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_proposal_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(TIMESTAMP)
    updated_at: Mapped[str] = mapped_column(TIMESTAMP)


class ShoppingCaseFulfillmentSelection(Base):
    """Revision-bound buyer selection bridging research to guarded cart execution."""

    __tablename__ = "shopping_case_fulfillment_selections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", "revision", name="uq_case_fulfillment_revision"),
        UniqueConstraint(
            "tenant_id", "case_id", "selection_idempotency_key",
            name="uq_case_fulfillment_selection_idempotency",
        ),
    )
    selection_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text)
    case_id: Mapped[str] = mapped_column(Text)
    uid: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    choice: Mapped[str] = mapped_column(Text)
    preferred_sku: Mapped[str] = mapped_column(Text)
    requested_quantity: Mapped[int] = mapped_column(Integer)
    available_now: Mapped[int] = mapped_column(Integer)
    offers_json: Mapped[list] = mapped_column(JSON)
    selection_idempotency_key: Mapped[str] = mapped_column(Text)
    selected_offer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    cart_plan_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cart_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(TIMESTAMP)
    updated_at: Mapped[str] = mapped_column(TIMESTAMP)


class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id: Mapped[str] = mapped_column(Text, ForeignKey("products.id", ondelete="CASCADE"))
    stock: Mapped[int] = mapped_column(Integer)
    warehouse: Mapped[str] = mapped_column(Text, default="default")
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class DraftOrder(Base):
    __tablename__ = "draft_orders"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id: Mapped[str | None] = mapped_column(Text, ForeignKey("customers.id"), nullable=True)
    line_items: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_order_id: Mapped[str | None] = mapped_column(Text, ForeignKey("draft_orders.id"), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(Text, ForeignKey("customers.id"), nullable=True)
    total_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, default="USD")
    status: Mapped[str] = mapped_column(Text, default="pending_payment")
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    # Attribution: links an order back to the recommendation decision that produced it
    # (populated by the cart trace at order creation — edge E1). Nullable so non-attributed
    # / direct orders are unaffected.
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_id: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReturnCase(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    guest_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="open")
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(Text, ForeignKey("cases.id", ondelete="CASCADE"))
    bundle_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)


class HumanReviewTask(Base):
    __tablename__ = "human_review_tasks"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(Text, ForeignKey("cases.id", ondelete="CASCADE"))
    decision_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)
