"""Run lifecycle: submission, state transitions, retries. All status changes go through here."""
from __future__ import annotations

import itertools
import uuid
from typing import Any

from sqlalchemy.orm import Session

from . import monitoring as m
from .config import get_settings
from .job_queue import get_queue
from .models import ACTIVE, TERMINAL, Experiment, Run, RunEvent, RunStatus, User, utcnow

# Allowed transitions. Anything else is rejected (e.g. a late "running" heartbeat after cancel).
TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.queued: {RunStatus.scheduled, RunStatus.cancelled},
    RunStatus.scheduled: {RunStatus.running, RunStatus.succeeded, RunStatus.failed, RunStatus.stalled,
                          RunStatus.cancelled, RunStatus.queued},
    RunStatus.running: {RunStatus.succeeded, RunStatus.failed, RunStatus.stalled, RunStatus.cancelled,
                        RunStatus.queued},
    RunStatus.succeeded: set(),
    RunStatus.failed: {RunStatus.queued},  # manual retry
    RunStatus.stalled: {RunStatus.queued},
    RunStatus.cancelled: {RunStatus.queued},
}


class InvalidTransition(Exception):
    pass


def log_event(db: Session, run: Run, kind: str, message: str) -> None:
    db.add(RunEvent(run_id=run.id, kind=kind, message=message))


def transition(db: Session, run: Run, new: RunStatus, message: str = "", *, error: str | None = None,
               allow_retry: bool = True) -> Run:
    old = run.status
    if new == old:
        return run
    if new not in TRANSITIONS[old]:
        raise InvalidTransition(f"run {run.id}: {old.value} -> {new.value} not allowed")

    now = utcnow()
    run.status = new
    if new == RunStatus.running and run.started_at is None:
        run.started_at = now
        run.last_heartbeat_at = now
    if new == RunStatus.scheduled:
        run.last_heartbeat_at = now  # start the stall clock at dispatch time
    if error:
        run.error = error[:4000]
    log_event(db, run, "status", f"{old.value} → {new.value}" + (f": {message}" if message else ""))

    if new in TERMINAL:
        run.finished_at = now
        m.RUNS_FINISHED.labels(new.value).inc()
        if run.duration_s is not None:
            m.RUN_DURATION.labels(new.value).observe(run.duration_s)
        if new in (RunStatus.failed, RunStatus.stalled) and allow_retry and run.attempt < run.max_retries:
            _requeue(db, run, f"automatic retry {run.attempt + 1}/{run.max_retries}")
            m.RUNS_RETRIED.inc()
    return run


def _requeue(db: Session, run: Run, reason: str) -> None:
    old = run.status
    run.status = RunStatus.queued
    run.attempt += 1
    run.executor_ref = None
    run.started_at = run.finished_at = run.last_heartbeat_at = None
    run.progress = 0.0
    log_event(db, run, "retry", f"{old.value} → queued ({reason})")
    db.flush()
    get_queue().enqueue(run.id, run.priority)


def retry(db: Session, run: Run) -> Run:
    if run.status not in TRANSITIONS or RunStatus.queued not in TRANSITIONS[run.status] or run.status in ACTIVE:
        raise InvalidTransition(f"cannot retry a {run.status.value} run")
    _requeue(db, run, "manual retry")
    return run


def submit_run(db: Session, exp: Experiment, user: User, *, config: dict[str, Any], name: str | None = None,
               priority: int = 0, resources: dict | None = None, max_retries: int | None = None,
               sweep_id: str | None = None) -> Run:
    s = get_settings()
    n = len(exp.runs) + 1
    run = Run(
        experiment_id=exp.id,
        name=name or f"{exp.name}-{n}",
        config={**(exp.base_config or {}), **config},
        priority=priority,
        resources=resources or {},
        max_retries=s.max_retries_default if max_retries is None else max_retries,
        executor=s.executor,
        sweep_id=sweep_id,
        created_by_id=user.id,
    )
    db.add(run)
    db.flush()
    log_event(db, run, "status", f"submitted by {user.email} (priority {priority})")
    m.RUNS_SUBMITTED.labels(exp.name).inc()
    return run


def expand_grid(grid: dict[str, list[Any]], max_runs: int) -> list[dict[str, Any]]:
    keys = sorted(grid)
    combos = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(grid[k] for k in keys))]
    if len(combos) > max_runs:
        raise ValueError(f"sweep expands to {len(combos)} runs (max_runs={max_runs})")
    return combos


def submit_sweep(db: Session, exp: Experiment, user: User, *, grid: dict, base: dict, priority: int,
                 resources: dict, max_runs: int) -> list[Run]:
    sweep_id = uuid.uuid4().hex[:8]
    runs = []
    for i, combo in enumerate(expand_grid(grid, max_runs), 1):
        label = ",".join(f"{k}={v}" for k, v in combo.items())
        runs.append(submit_run(db, exp, user, config={**base, **combo}, name=f"sweep-{sweep_id}-{i} [{label}]",
                               priority=priority, resources=resources, sweep_id=sweep_id))
    return runs


def enqueue_after_commit(runs: list[Run]) -> None:
    q = get_queue()
    for r in runs:
        q.enqueue(r.id, r.priority)
