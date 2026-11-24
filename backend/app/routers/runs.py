import math
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import services
from ..auth import current_user, require_role
from ..config import get_settings
from ..db import get_db
from ..executors import get_executor
from ..job_queue import get_queue
from ..models import ACTIVE, MetricPoint, Role, Run, RunStatus, User
from ..schemas import ArtifactOut, CompareOut, EventOut, RunOut

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _v(x: float):
    """NaN/Inf are stored (they signal divergence) but JSON cannot carry them."""
    return x if math.isfinite(x) else None


def _get(db: Session, run_id: int) -> Run:
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


def _can_modify(user: User, run: Run) -> None:
    if user.role != Role.admin and run.created_by_id != user.id:
        raise HTTPException(403, "Only the run's creator or an admin can do that")


@router.get("", response_model=list[RunOut])
def list_runs(status: RunStatus | None = None, limit: int = Query(100, le=500), db: Session = Depends(get_db),
              _: User = Depends(current_user)):
    q = select(Run).order_by(Run.id.desc()).limit(limit)
    if status:
        q = q.where(Run.status == status)
    return db.scalars(q).all()


@router.get("/compare", response_model=CompareOut)
def compare(ids: str = Query(..., description="comma-separated run ids"), db: Session = Depends(get_db),
            _: User = Depends(current_user)):
    try:
        run_ids = [int(x) for x in ids.split(",") if x.strip()][:12]
    except ValueError:
        raise HTTPException(422, "ids must be integers")
    runs = db.scalars(select(Run).where(Run.id.in_(run_ids)).options(selectinload(Run.metrics))).all()
    series: dict[int, dict[str, list[list]]] = {}
    keys: set[str] = set()
    for r in runs:
        d = defaultdict(list)
        for p in r.metrics:
            d[p.key].append([p.step, _v(p.value)])
            keys.add(p.key)
        series[r.id] = dict(d)
    cfg_keys = sorted({k for r in runs for k in r.config})
    differing = [k for k in cfg_keys if len({repr(r.config.get(k)) for r in runs}) > 1]
    return CompareOut(runs=runs, metric_keys=sorted(keys), series=series, config_keys=cfg_keys,
                      differing_config_keys=differing)


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _get(db, run_id)


@router.get("/{run_id}/metrics")
def run_metrics(run_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _get(db, run_id)
    out: dict[str, list[list[float]]] = defaultdict(list)
    for p in db.scalars(select(MetricPoint).where(MetricPoint.run_id == run_id).order_by(MetricPoint.step)):
        out[p.key].append([p.step, _v(p.value)])
    return out


@router.get("/{run_id}/events", response_model=list[EventOut])
def run_events(run_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _get(db, run_id).events


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
def run_artifacts(run_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _get(db, run_id).artifacts


@router.get("/{run_id}/artifacts/{artifact_id}/download")
def download_artifact(run_id: int, artifact_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    art = next((a for a in _get(db, run_id).artifacts if a.id == artifact_id), None)
    if not art:
        raise HTTPException(404, "Artifact not found")
    root = Path(get_settings().artifact_dir).resolve()
    # Trainers report paths relative to their artifact dir (/artifacts in pods).
    rel = art.uri.removeprefix("file://").removeprefix("/artifacts/")
    path = (root / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    if not path.is_relative_to(root) or not path.exists():
        raise HTTPException(404, "Artifact file not available on this server")
    return FileResponse(path, filename=art.name)


@router.get("/{run_id}/logs", response_class=PlainTextResponse)
def run_logs(run_id: int, tail: int = Query(300, le=5000), db: Session = Depends(get_db),
             _: User = Depends(current_user)):
    run = _get(db, run_id)
    if not run.executor_ref:
        return "(run has not started yet)"
    try:
        return get_executor(run.executor).logs(run.executor_ref, tail) or "(no output yet)"
    except Exception as e:
        return f"(logs unavailable: {e})"


@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(Role.researcher))):
    run = _get(db, run_id)
    _can_modify(user, run)
    if run.status == RunStatus.queued:
        get_queue().remove(run.id)
    elif run.status in ACTIVE and run.executor_ref:
        get_executor(run.executor).cancel(run.executor_ref)
    try:
        services.transition(db, run, RunStatus.cancelled, f"cancelled by {user.email}", allow_retry=False)
    except services.InvalidTransition as e:
        raise HTTPException(409, str(e))
    db.commit()
    return run


@router.post("/{run_id}/retry", response_model=RunOut)
def retry(run_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(Role.researcher))):
    run = _get(db, run_id)
    _can_modify(user, run)
    try:
        services.retry(db, run)
    except services.InvalidTransition as e:
        raise HTTPException(409, str(e))
    db.commit()
    return run
