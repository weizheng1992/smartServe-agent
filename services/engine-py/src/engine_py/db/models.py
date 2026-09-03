"""SQLAlchemy 模型 — schema 唯一事实源(Phase 3 翻转后 Alembic 拥有 migrations)。

列定义逐列对齐 packages/db/src/schema.ts + migrateColumns.ts 的幂等 ALTER
(orders.shipping_address/recipient_name/phone、pending_approvals.business_id/reason、
threads.user_id 去 FK 化)。变更表结构时:先改本文件,再 ``alembic revision
--autogenerate``。禁止在模型层写业务逻辑。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


# ============ 用户与会话 ============


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(Text)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))
    assigned_operator_id: Mapped[str | None] = mapped_column(Text)
    unread_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    tags: Mapped[list | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("threads_biz_status_idx", Thread.business_id, Thread.status)
Index("threads_updated_at_idx", Thread.updated_at)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        Text, ForeignKey("threads.id"), nullable=False
    )
    business_id: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    thought_steps: Mapped[dict | None] = mapped_column(JSONB)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    cards: Mapped[list | None] = mapped_column(JSONB)
    operator_info: Mapped[dict | None] = mapped_column(JSONB)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("messages_thread_idx", Message.thread_id)
Index("messages_biz_thread_idx", Message.business_id, Message.thread_id)


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    tracking_number: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_delivery: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str | None] = mapped_column(Text)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    total_amount: Mapped[float | None] = mapped_column(Float)
    address_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    shipping_address: Mapped[str | None] = mapped_column(Text)  # migrateColumns 幂等补充
    recipient_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    manager_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, server_default=text("'general'"))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float | None] = mapped_column(Float, server_default=text("0.0"))
    stock: Mapped[int | None] = mapped_column(Integer, server_default=text("99"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey("orders.order_id"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("products.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_at_purchase: Mapped[float] = mapped_column(Float, nullable=False)
    cost_at_purchase: Mapped[float | None] = mapped_column(Float, server_default=text("0.0"))


class SessionMetric(Base):
    __tablename__ = "session_metrics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, ForeignKey("threads.id"), nullable=False)
    total_tokens: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    calculated_cost_usd: Mapped[float | None] = mapped_column(Float, server_default=text("0.0"))
    node_transitions_count: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    global_transitions_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    tool_errors_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, server_default=text("0"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class BadcaseCandidate(Base):
    """Bad-Case 候选池(第五阶段半自动闭环)。

    只存信号引用,不复制原始会话;一切信号经人工 triage 定性后才可能转为回归 case。
    """

    __tablename__ = "badcase_candidates"
    __table_args__ = (Index("ix_badcase_candidates_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    signal_source: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_ref: Mapped[str] = mapped_column(Text, nullable=False)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_class: Mapped[str | None] = mapped_column(Text, server_default=text("'neutral'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'candidate'"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class LongMemoryFact(Base):
    __tablename__ = "long_memory_facts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    business_id: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, server_default=text("'global'"))
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text)  # JSON 串(与 TS 侧序列化方式一致)
    type: Mapped[str | None] = mapped_column(Text, server_default=text("'fact'"))
    confidence: Mapped[float | None] = mapped_column(Float, server_default=text("1.0"))
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'approved'"))
    source: Mapped[str | None] = mapped_column(Text, server_default=text("'regex_fallback'"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


Index("long_facts_user_scope_biz_idx", LongMemoryFact.user_id, LongMemoryFact.scope, LongMemoryFact.business_id)


class TaskMemoryRow(Base):
    __tablename__ = "task_memory"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str] = mapped_column(Text, ForeignKey("threads.id"), nullable=False)
    pending_intents: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class EpisodicEventRow(Base):
    __tablename__ = "episodic_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text, ForeignKey("threads.id"))
    business_id: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, server_default=text("'global'"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text)  # JSON 串
    importance: Mapped[int | None] = mapped_column(Integer, server_default=text("3"))
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("episodic_user_scope_biz_idx", EpisodicEventRow.user_id, EpisodicEventRow.scope, EpisodicEventRow.business_id)


class RagDocumentRow(Base):
    __tablename__ = "rag_documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    contextual_summary: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[str | None] = mapped_column(Text)  # JSON 串
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("rag_business_idx", RagDocumentRow.business_id)


class IntentLog(Base):
    __tablename__ = "intent_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str | None] = mapped_column(Text, ForeignKey("threads.id"))
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_intents: Mapped[list] = mapped_column(JSONB, nullable=False)
    method: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    actual_outcome: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class LowConfidenceLog(Base):
    __tablename__ = "low_confidence_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str | None] = mapped_column(Text, ForeignKey("threads.id"))
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    candidates: Mapped[dict | None] = mapped_column(JSONB)
    reviewed: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class PendingApproval(Base):
    __tablename__ = "pending_approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str] = mapped_column(Text, ForeignKey("threads.id"), nullable=False)
    business_id: Mapped[str | None] = mapped_column(Text)  # migrateColumns 幂等补充
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    action_payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'waiting'"))
    reason: Mapped[str | None] = mapped_column(Text)  # migrateColumns 幂等补充
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class ApprovalOutboxEvent(Base):
    __tablename__ = "approval_outbox_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    approval_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), nullable=False)
    retry_count: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("approval_outbox_status_idx", ApprovalOutboxEvent.status, ApprovalOutboxEvent.created_at)
Index("approval_outbox_approval_idx", ApprovalOutboxEvent.approval_id)


class BusinessConfigRow(Base):
    __tablename__ = "business_configs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("business_config_version_idx", BusinessConfigRow.business_id, BusinessConfigRow.version)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    git_commit: Mapped[str | None] = mapped_column(Text)
    avg_answer_quality: Mapped[float | None] = mapped_column(Float)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float)
    total_cost_usd: Mapped[float | None] = mapped_column(Float)
    pass_rate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False)
    case_name: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    metrics: Mapped[dict | None] = mapped_column(JSONB)


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str | None] = mapped_column(Text, ForeignKey("threads.id"))
    node: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("llm_log_thread_idx", LlmCallLog.thread_id)


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_id: Mapped[str] = mapped_column(Text, ForeignKey("threads.id"), nullable=False)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'pending'"))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan_tier: Mapped[str] = mapped_column(Text, server_default=text("'free'"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class TenantMember(Base):
    __tablename__ = "tenant_members"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class TenantConfig(Base):
    __tablename__ = "tenant_configs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    welcome_message: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float | None] = mapped_column(Float, server_default=text("0.7"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    spi_config: Mapped[dict | None] = mapped_column(JSONB)
    enabled_skills: Mapped[list | None] = mapped_column(JSONB)
    skills_config: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("tenant_config_biz_status_idx", TenantConfig.business_id, TenantConfig.status)


class TenantTool(Base):
    __tablename__ = "tenant_tools"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schema_: Mapped[dict] = mapped_column("schema", JSONB, nullable=False)
    auth_type: Mapped[str | None] = mapped_column(Text, server_default=text("'none'"))
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    requires_approval: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    enabled: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class UserAddress(Base):
    __tablename__ = "user_addresses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    receiver_name: Mapped[str] = mapped_column(Text, nullable=False)
    receiver_phone: Mapped[str] = mapped_column(Text, nullable=False)
    province: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str] = mapped_column(Text, nullable=False)
    detail_address: Mapped[str] = mapped_column(Text, nullable=False)
    full_address: Mapped[str] = mapped_column(Text, nullable=False)
    tag: Mapped[str | None] = mapped_column(Text, server_default=text("'home'"))
    is_default: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("user_address_biz_user_idx", UserAddress.business_id, UserAddress.user_id)


class ProductSku(Base):
    __tablename__ = "product_skus"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sku_code: Mapped[str] = mapped_column(Text, nullable=False)
    spec_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    cost_price: Mapped[float | None] = mapped_column(Float, server_default=text("0.0"))
    stock: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    image_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'active'"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("product_skus_biz_product_idx", ProductSku.business_id, ProductSku.product_id)
Index("product_skus_code_idx", ProductSku.sku_code)


class LogisticsPackage(Base):
    __tablename__ = "logistics_packages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(
        Text, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False
    )
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    carrier_code: Mapped[str] = mapped_column(Text, nullable=False)
    tracking_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'in_transit'"), nullable=False)
    current_location: Mapped[str | None] = mapped_column(Text)
    courier_name: Mapped[str | None] = mapped_column(Text)
    courier_phone: Mapped[str | None] = mapped_column(Text)
    estimated_delivery: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("logistics_pkg_biz_order_idx", LogisticsPackage.business_id, LogisticsPackage.order_id)
Index("logistics_pkg_tracking_idx", LogisticsPackage.tracking_number)


class LogisticsTrack(Base):
    __tablename__ = "logistics_tracks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    package_id: Mapped[str] = mapped_column(
        Text, ForeignKey("logistics_packages.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("logistics_tracks_pkg_time_idx", LogisticsTrack.package_id, LogisticsTrack.occurred_at)


class ProductReview(Base):
    __tablename__ = "product_reviews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_name: Mapped[str | None] = mapped_column(Text)
    user_avatar: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    images: Mapped[list | None] = mapped_column(JSONB)
    fit_feedback: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(Text, server_default=text("'positive'"))
    merchant_reply: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("product_reviews_biz_product_idx", ProductReview.business_id, ProductReview.product_id)


class AfterSaleTicket(Base):
    __tablename__ = "after_sale_tickets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(Text, ForeignKey("orders.order_id"), nullable=False)
    order_item_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reason_description: Mapped[str | None] = mapped_column(Text)
    refund_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending_review'"), nullable=False)
    return_tracking_number: Mapped[str | None] = mapped_column(Text)
    human_approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("after_sale_biz_order_idx", AfterSaleTicket.business_id, AfterSaleTicket.order_id)
Index("after_sale_biz_user_idx", AfterSaleTicket.business_id, AfterSaleTicket.user_id)


class AfterSaleLog(Base):
    __tablename__ = "after_sale_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ticket_id: Mapped[str] = mapped_column(
        Text, ForeignKey("after_sale_tickets.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("after_sale_logs_ticket_idx", AfterSaleLog.ticket_id)


class GuardrailRule(Base):
    __tablename__ = "guardrail_rules"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    business_id: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'all'"))
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'block'"))
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'high'"))
    is_enabled: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("guardrail_rules_biz_idx", GuardrailRule.business_id)


class TenantBillingQuota(Base):
    __tablename__ = "tenant_billing_quotas"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    monthly_limit_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5000000")
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class IntentExemplar(Base):
    __tablename__ = "intent_exemplars"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    intent_name: Mapped[str] = mapped_column(Text, nullable=False)
    example_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


Index("intent_exemplars_biz_idx", IntentExemplar.business_id, IntentExemplar.intent_name)


class EvalRunRecordRow(Base):
    __tablename__ = "eval_run_records"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_name: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_name: Mapped[str] = mapped_column(Text, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("50"))
    tool_accuracy: Mapped[float | None] = mapped_column(Float, server_default=text("0.95"))
    rag_faithfulness: Mapped[float | None] = mapped_column(Float, server_default=text("0.92"))
    hitl_trigger_rate: Mapped[float | None] = mapped_column(Float, server_default=text("0.12"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'completed'"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))
