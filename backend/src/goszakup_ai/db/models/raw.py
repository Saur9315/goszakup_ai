from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from goszakup_ai.db.base import Base

SCHEMA = {"schema": "raw"}


class RawObject(Base):
    __tablename__ = "ows_object"
    __table_args__ = SCHEMA

    entity: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    index_date: Mapped[datetime | None]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
