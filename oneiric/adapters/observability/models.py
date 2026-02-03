from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TraceModel(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    trace_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_state: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default="all-MiniLM-L6-v2"
    )
    embedding_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    __table_args__ = (
        Index("ix_traces_trace_id", "trace_id"),
        Index("ix_traces_name", "name"),
        Index("ix_traces_start_time", "start_time"),
        Index("ix_traces_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<TraceModel(id={self.id!r}, trace_id={self.trace_id!r}, "
            f"name={self.name!r}, status={self.status!r})>"
        )


class MetricModel(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    labels: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_metrics_name", "name"),
        Index("ix_metrics_timestamp", "timestamp"),
        Index("ix_metrics_type", "type"),
    )

    def __repr__(self) -> str:
        return (
            f"<MetricModel(id={self.id!r}, name={self.name!r}, "
            f"type={self.type!r}, value={self.value!r})>"
        )


class LogModel(Base):
    __tablename__ = "logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    level: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_attributes: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    span_attributes: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)

    __table_args__ = (
        Index("ix_logs_timestamp", "timestamp"),
        Index("ix_logs_trace_id", "trace_id"),
        Index("ix_logs_level", "level"),
    )

    def __repr__(self) -> str:
        return (
            f"<LogModel(id={self.id!r}, timestamp={self.timestamp!r}, "
            f"level={self.level!r}, message={self.message[:50]!r}...)>"
        )
