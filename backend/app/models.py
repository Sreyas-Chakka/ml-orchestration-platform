"""Relational model: users -> experiments -> runs -> (metrics, artifacts, events, analyses)."""
from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(str, enum.Enum):
    admin = "admin"
    researcher = "researcher"
    viewer = "viewer"


class RunStatus(str, enum.Enum):
    queued = "queued"
    scheduled = "scheduled"  # handed to the executor, pod/process starting
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    stalled = "stalled"
    cancelled = "cancelled"


TERMINAL = {RunStatus.succeeded, RunStatus.failed, RunStatus.stalled, RunStatus.cancelled}
ACTIVE = {RunStatus.scheduled, RunStatus.running}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.viewer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # Default training entrypoint + config every run inherits (and may override).
    entrypoint: Mapped[str] = mapped_column(String(255), default="mlp_classifier")
    base_config: Mapped[dict] = mapped_column(JSON, default=dict)
    primary_metric: Mapped[str] = mapped_column(String(64), default="val_accuracy")
    metric_goal: Mapped[str] = mapped_column(String(8), default="max")  # max | min
    tags: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship()
    runs: Mapped[list[Run]] = relationship(back_populates="experiment", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, native_enum=False), default=RunStatus.queued, index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    resources: Mapped[dict] = mapped_column(JSON, default=dict)  # {"cpu": "500m", "memory": "512Mi"}
    sweep_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    executor: Mapped[str] = mapped_column(String(32), default="local")
    executor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # pid or k8s job name
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # final metrics
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    experiment: Mapped[Experiment] = relationship(back_populates="runs")
    created_by: Mapped[User] = relationship()
    metrics: Mapped[list[MetricPoint]] = relationship(cascade="all, delete-orphan", order_by="MetricPoint.step")
    artifacts: Mapped[list[Artifact]] = relationship(cascade="all, delete-orphan")
    events: Mapped[list[RunEvent]] = relationship(cascade="all, delete-orphan", order_by="RunEvent.id")

    @property
    def duration_s(self) -> float | None:
        if not self.started_at:
            return None
        end = self.finished_at or utcnow()
        start = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        return (end - start).total_seconds()


class MetricPoint(Base):
    __tablename__ = "metric_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    step: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_metric_run_key_step", "run_id", "key", "step"),)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="model")  # model | plot | data | other
    uri: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunEvent(Base):
    """Audit trail of state transitions and notable events for a run."""

    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # status | retry | alert | info
    message: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Analysis(Base):
    """Stored output of the LLM analyst for an experiment (or a subset of its runs)."""

    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    run_ids: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32))  # claude | heuristic
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    best_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anomalies: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
