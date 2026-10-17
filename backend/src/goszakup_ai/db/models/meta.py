import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from goszakup_ai.db.base import Base

SCHEMA = {"schema": "meta"}
SYNC_LOCK_CLASS = 7301


class ScopeBin(Base):
    __tablename__ = "scope_bin"
    __table_args__ = SCHEMA

    bin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = SCHEMA

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_index_date: Mapped[datetime | None]
    last_success_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rows_loaded: Mapped[int] = mapped_column(BigInteger, default=0)


class GapMiss(Base):
    __tablename__ = "gap_miss"
    __table_args__ = SCHEMA

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncRun(Base):
    __tablename__ = "sync_run"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    command: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class DqCheckResult(Base):
    __tablename__ = "dq_check_result"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    check_name: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    failed_count: Mapped[int] = mapped_column(BigInteger)
    total_count: Mapped[int] = mapped_column(BigInteger)
    sample: Mapped[list[Any] | None] = mapped_column(JSONB)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    __tablename__ = "analysis_run"
    __table_args__ = SCHEMA

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    question: Mapped[str] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(16))
    language: Mapped[str | None] = mapped_column(String(4))
    intent: Mapped[str | None] = mapped_column(String(32))
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tool_results: Mapped[list[Any] | None] = mapped_column(JSONB)
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    llm_fallback: Mapped[bool | None]
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    timings_ms: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentThread(Base):
    __tablename__ = "agent_thread"
    __table_args__ = (Index("ix_meta_agent_thread_user", "user_id", "updated_at"), SCHEMA)

    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("meta.app_user.id"))
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
