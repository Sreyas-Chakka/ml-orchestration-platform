from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import Role, RunStatus


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: Role
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=6)
    role: Role = Role.viewer


class RoleUpdate(BaseModel):
    role: Role


# ---- experiments -----------------------------------------------------------
class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    entrypoint: str = "mlp_classifier"
    base_config: dict[str, Any] = {}
    primary_metric: str = "val_accuracy"
    metric_goal: str = Field("max", pattern="^(max|min)$")
    tags: list[str] = []


class ExperimentOut(ORM):
    id: int
    name: str
    description: str
    entrypoint: str
    base_config: dict
    primary_metric: str
    metric_goal: str
    tags: list
    owner_id: int
    created_at: datetime
    run_counts: dict[str, int] = {}
    best_run_id: int | None = None
    best_value: float | None = None


# ---- runs ------------------------------------------------------------------
class RunCreate(BaseModel):
    name: str | None = None
    config: dict[str, Any] = {}
    priority: int = Field(0, ge=-10, le=10)
    resources: dict[str, str] = {}
    max_retries: int | None = Field(None, ge=0, le=5)


class SweepCreate(BaseModel):
    """Grid sweep: the cartesian product of `grid` values is launched as individual runs."""

    grid: dict[str, list[Any]]
    base: dict[str, Any] = {}
    priority: int = Field(0, ge=-10, le=10)
    resources: dict[str, str] = {}
    max_runs: int = Field(32, ge=1, le=128)


class RunOut(ORM):
    id: int
    experiment_id: int
    name: str
    status: RunStatus
    config: dict
    priority: int
    resources: dict
    sweep_id: str | None
    attempt: int
    max_retries: int
    executor: str
    executor_ref: str | None
    error: str | None
    summary: dict
    progress: float
    created_by_id: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_heartbeat_at: datetime | None
    duration_s: float | None


class MetricIn(BaseModel):
    step: int
    values: dict[str, float]


class MetricsBatchIn(BaseModel):
    points: list[MetricIn]
    progress: float | None = None


class ArtifactIn(BaseModel):
    name: str
    kind: str = "model"
    uri: str
    size_bytes: int = 0
    sha256: str = ""
    meta: dict[str, Any] = {}


class ArtifactOut(ORM, ArtifactIn):
    id: int
    run_id: int
    created_at: datetime


class StatusIn(BaseModel):
    status: RunStatus
    error: str | None = None
    summary: dict[str, float] = {}


class EventOut(ORM):
    id: int
    kind: str
    message: str
    ts: datetime


class CompareOut(BaseModel):
    runs: list[RunOut]
    metric_keys: list[str]
    series: dict[int, dict[str, list[list[float | None]]]]  # run_id -> key -> [[step, value], ...]
    config_keys: list[str]
    differing_config_keys: list[str]


# ---- analysis --------------------------------------------------------------
class AnalyzeIn(BaseModel):
    run_ids: list[int] | None = None


class AnalysisOut(ORM):
    id: int
    experiment_id: int
    run_ids: list
    source: str
    model: str | None
    summary: str
    best_run_id: int | None
    anomalies: list
    recommendations: list
    created_at: datetime
