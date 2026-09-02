"""SQLAlchemy 模型投影 — 列定义逐列对齐 packages/db/src/schema.ts。

⚠️ Drizzle 拥有 schema 与 migrations(db:push);此处只做只读/写入映射,
严禁在本层发起任何 DDL。未列出的列以 ``DeferredReflection`` 之外的方式
按需补充 —— 保持与 schema.ts 同步是 Phase 3 翻转前的硬约束。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


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


class EpisodicEventRow(Base):
    __tablename__ = "episodic_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(Text)
    business_id: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, server_default=text("'global'"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text)  # JSON 串
    importance: Mapped[int | None] = mapped_column(Integer, server_default=text("3"))
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


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


class SessionMetric(Base):
    __tablename__ = "session_metrics"

    id: Mapped[uuid.UUID] = _uuid_pk()
    business_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    total_tokens: Mapped[int | None] = mapped_column(Integer, server_default=text("0"))
    calculated_cost_usd: Mapped[float | None] = mapped_column(Float, server_default=text("0.0"))
    node_transitions_count: Mapped[int | None] = mapped_column(Integer, server_default=text("1"))
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, server_default=text("0"))
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
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
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


class TaskMemoryRow(Base):
    __tablename__ = "task_memory"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    pending_intents: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class IntentLog(Base):
    __tablename__ = "intent_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str | None] = mapped_column(Text)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_intents: Mapped[list] = mapped_column(JSONB, nullable=False)
    method: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    actual_outcome: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


class LowConfidenceLog(Base):
    __tablename__ = "low_confidence_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str | None] = mapped_column(Text)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    candidates: Mapped[dict | None] = mapped_column(JSONB)
    reviewed: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("now()"))


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


class PendingApproval(Base):
    """business_id / reason 列由 packages/db/src/migrateColumns.ts 的幂等 ALTER 补充。"""

    __tablename__ = "pending_approvals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    business_id: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    action_payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str | None] = mapped_column(Text, server_default=text("'waiting'"))
    reason: Mapped[str | None] = mapped_column(Text)
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
