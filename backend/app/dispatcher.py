"""The scheduler loop.

Each tick:
  1. reconcile  — compare every active run with what the executor reports (pod crashed, image
                  pull failed, process exited without reporting, ...).
  2. watchdog   — runs whose heartbeat is older than STALL_TIMEOUT are marked STALLED and killed.
  3. dispatch   — pop jobs from the priority queue while there is spare capacity and launch them.
  4. gauges     — refresh Prometheus gauges from the database.

Runs either embedded in the API process (dev) or as its own deployment (`python -m app.worker`).
With Redis, a leader lock ensures only one replica schedules at a time.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import monitoring as m
from .auth import create_run_token
from .config import get_settings
from .db import SessionLocal
from .executors import get_executor
from .executors.base import LaunchSpec
from .job_queue import get_queue
from .models import ACTIVE, Run, RunStatus, utcnow
from .services import InvalidTransition, log_event, transition

log = logging.getLogger("mlops.dispatcher")


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


class Dispatcher:
    def __init__(self):
        self.s = get_settings()
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self.loop, name="dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def loop(self) -> None:
        log.info("dispatcher %s started (executor=%s, capacity=%d)", self.worker_id, self.s.executor,
                 self.s.max_concurrent_runs)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("dispatcher tick failed")
            self._stop.wait(self.s.dispatch_interval_s)

    def recover(self) -> None:
        """Re-enqueue queued runs (the in-memory queue does not survive restarts; ZADD NX is idempotent)."""
        with SessionLocal() as db:
            q = get_queue()
            for run in db.scalars(select(Run).where(Run.status == RunStatus.queued)):
                q.enqueue(run.id, run.priority)

    # ---- one scheduling pass -------------------------------------------------
    def tick(self) -> None:
        m.DISPATCHER_LAST_TICK.set(time.time())
        if not get_queue().acquire_leader(self.worker_id, ttl_s=max(10, int(self.s.dispatch_interval_s * 5))):
            return
        with SessionLocal() as db:
            self.reconcile(db)
            self.watchdog(db)
            self.dispatch(db)
            self.refresh_gauges(db)

    def reconcile(self, db: Session) -> None:
        for run in db.scalars(select(Run).where(Run.status.in_(ACTIVE))).all():
            if not run.executor_ref:
                continue
            try:
                state = get_executor(run.executor).poll(run.executor_ref)
            except Exception as e:
                log.warning("poll failed for run %s: %s", run.id, e)
                continue
            try:
                if state.phase == "failed":
                    transition(db, run, RunStatus.failed, state.message, error=state.message)
                elif state.phase == "succeeded":
                    # Trainer exited cleanly but its final status callback never landed.
                    transition(db, run, RunStatus.succeeded, "executor reported success")
                elif state.phase == "running" and run.status == RunStatus.scheduled:
                    pass  # wait for the trainer's own "running" callback
            except InvalidTransition:
                pass
            db.commit()

    def watchdog(self, db: Session) -> None:
        now = utcnow()
        for run in db.scalars(select(Run).where(Run.status.in_(ACTIVE))).all():
            hb = _aware(run.last_heartbeat_at)
            if hb is None:
                continue
            # Pods get extra grace to pull images and get scheduled.
            limit = self.s.stall_timeout_s * (5 if run.status == RunStatus.scheduled else 1)
            age = (now - hb).total_seconds()
            if age > limit:
                msg = f"no heartbeat for {int(age)}s (limit {limit}s)"
                log.warning("run %s stalled: %s", run.id, msg)
                m.STALL_DETECTIONS.inc()
                log_event(db, run, "alert", f"watchdog: {msg}")
                ref = run.executor_ref
                transition(db, run, RunStatus.stalled, msg, error=msg)
                db.commit()
                if ref:
                    try:
                        get_executor(run.executor).cancel(ref)
                    except Exception as e:
                        log.warning("failed to kill stalled run %s: %s", run.id, e)

    def dispatch(self, db: Session) -> None:
        q = get_queue()
        active = db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE))) or 0
        capacity = self.s.max_concurrent_runs - active
        while capacity > 0:
            run_id = q.pop(self.worker_id)
            if run_id is None:
                break
            run = db.get(Run, run_id)
            if run is None or run.status != RunStatus.queued:
                q.ack(run_id)  # cancelled or deleted while waiting
                continue
            exp = run.experiment
            spec = LaunchSpec(
                run_id=run.id,
                entrypoint=exp.entrypoint,
                config=run.config,
                resources=run.resources,
                attempt=run.attempt,
                env={
                    "MLOPS_API_URL": self.s.callback_url,
                    "MLOPS_RUN_ID": str(run.id),
                    "MLOPS_RUN_TOKEN": create_run_token(run.id),
                    "MLOPS_ARTIFACT_DIR": self.s.artifact_dir,
                },
            )
            try:
                run.executor = self.s.executor
                run.executor_ref = get_executor(run.executor).launch(spec)
                created = _aware(run.created_at)
                m.QUEUE_WAIT.observe((utcnow() - created).total_seconds())
                transition(db, run, RunStatus.scheduled, f"launched on {run.executor} as {run.executor_ref}")
            except Exception as e:
                log.exception("launch failed for run %s", run.id)
                m.DISPATCH_ERRORS.inc()
                run.status = RunStatus.scheduled  # route through the normal failure path (incl. retries)
                transition(db, run, RunStatus.failed, "launch failed", error=f"launch failed: {e}")
            db.commit()
            q.ack(run_id)
            capacity -= 1

    def refresh_gauges(self, db: Session) -> None:
        counts = dict(db.execute(select(Run.status, func.count()).group_by(Run.status)).all())
        for st in RunStatus:
            m.RUNS_BY_STATUS.labels(st.value).set(counts.get(st, 0))
        m.ACTIVE_RUNS.set(sum(counts.get(s, 0) for s in ACTIVE))
        m.QUEUE_DEPTH.set(get_queue().depth())
        m.CAPACITY.set(self.s.max_concurrent_runs)
        oldest = db.scalar(select(func.min(Run.last_heartbeat_at)).where(Run.status == RunStatus.running))
        m.OLDEST_HEARTBEAT_AGE.set((utcnow() - _aware(oldest)).total_seconds() if oldest else 0)
