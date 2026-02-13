from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import TIMESTAMP, JSON, Boolean, Integer, Text, ForeignKey
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
