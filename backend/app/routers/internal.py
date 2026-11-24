"""Callbacks from training containers. Authenticated with the per-run JWT, never a user token."""
import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..auth import run_identity
from ..db import get_db
from ..models import TERMINAL, Artifact, MetricPoint, Run, RunStatus, utcnow
from ..schemas import ArtifactIn, MetricsBatchIn, StatusIn

router = APIRouter(prefix="/api/internal/runs", tags=["trainer callbacks"])


def _active_run(db: Session, run_id: int) -> Run:
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status in TERMINAL:
        # e.g. the watchdog or a user already ended this run: tell the trainer to stop.
        raise HTTPException(409, f"Run is {run.status.value}; stop training")
    return run


@router.post("/{run_id}/heartbeat")
def heartbeat(run_id: int = Depends(run_identity), db: Session = Depends(get_db)):
    run = _active_run(db, run_id)
    run.last_heartbeat_at = utcnow()
    db.commit()
    return {"status": run.status.value}


@router.post("/{run_id}/status")
def report_status(body: StatusIn, run_id: int = Depends(run_identity), db: Session = Depends(get_db)):
    run = _active_run(db, run_id)
    if body.status not in (RunStatus.running, RunStatus.succeeded, RunStatus.failed):
        raise HTTPException(422, "Trainers may only report running/succeeded/failed")
    if body.summary:
        run.summary = {k: v for k, v in body.summary.items() if isinstance(v, (int, float)) and math.isfinite(v)}
    if body.status == RunStatus.succeeded:
        run.progress = 1.0
    run.last_heartbeat_at = utcnow()
    try:
        services.transition(db, run, body.status, "reported by trainer", error=body.error)
    except services.InvalidTransition as e:
        raise HTTPException(409, str(e))
    db.commit()
    return {"status": run.status.value}


@router.post("/{run_id}/metrics")
def log_metrics(body: MetricsBatchIn, run_id: int = Depends(run_identity), db: Session = Depends(get_db)):
    run = _active_run(db, run_id)
    n = 0
    for pt in body.points:
        for key, value in pt.values.items():
            # NaN is meaningful (divergence) and is stored; JSON clients receive it as null-safe float.
            db.add(MetricPoint(run_id=run.id, key=key[:64], step=pt.step, value=float(value)))
            n += 1
    if body.progress is not None:
        run.progress = max(0.0, min(1.0, body.progress))
    run.last_heartbeat_at = utcnow()
    db.commit()
    return {"accepted": n}


@router.post("/{run_id}/artifacts", status_code=201)
def register_artifact(body: ArtifactIn, run_id: int = Depends(run_identity), db: Session = Depends(get_db)):
    run = _active_run(db, run_id)
    art = Artifact(run_id=run.id, **body.model_dump())
    db.add(art)
    services.log_event(db, run, "info", f"artifact registered: {body.name} ({body.size_bytes} bytes)")
    db.commit()
    return {"id": art.id}
