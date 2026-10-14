from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from goszakup_ai.db.base import Base

SCHEMA = {"schema": "meta"}


class ScopeBin(Base):
    __tablename__ = "scope_bin"
    __table_args__ = SCHEMA

    bin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name_ru: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = SCHEMA

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_index_date: Mapped[datetime | None]
    last_success_at: Mapped[datetime] = mapped_column(server_default=func.now())
    rows_loaded: Mapped[int] = mapped_column(BigInteger, default=0)


class SyncRun(Base):
    __tablename__ = "sync_run"
    __table_args__ = SCHEMA

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    command: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
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
    checked_at: Mapped[datetime] = mapped_column(server_default=func.now())
