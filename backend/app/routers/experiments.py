from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import services
from ..analyst import analyze
from ..auth import current_user, require_role
from ..db import get_db
from ..models import Analysis, Experiment, Role, Run, RunStatus, User
from ..schemas import AnalysisOut, AnalyzeIn, ExperimentCreate, ExperimentOut, RunCreate, RunOut, SweepCreate

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _out(exp: Experiment) -> ExperimentOut:
    out = ExperimentOut.model_validate(exp)
    out.run_counts = dict(Counter(r.status.value for r in exp.runs))
    best = None
    for r in exp.runs:
        v = r.summary.get(exp.primary_metric) if r.status == RunStatus.succeeded else None
        if v is None:
            continue
        if best is None or (v > best[1] if exp.metric_goal == "max" else v < best[1]):
            best = (r.id, v)
    if best:
        out.best_run_id, out.best_value = best
    return out


def _get(db: Session, exp_id: int) -> Experiment:
    exp = db.get(Experiment, exp_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    return exp


@router.get("", response_model=list[ExperimentOut])
def list_experiments(db: Session = Depends(get_db), _: User = Depends(current_user)):
    exps = db.scalars(select(Experiment).options(selectinload(Experiment.runs)).order_by(Experiment.id.desc())).all()
    return [_out(e) for e in exps]


@router.post("", response_model=ExperimentOut, status_code=201)
def create_experiment(body: ExperimentCreate, db: Session = Depends(get_db),
                      user: User = Depends(require_role(Role.researcher))):
    exp = Experiment(**body.model_dump(), owner_id=user.id)
    db.add(exp)
    db.commit()
    return _out(exp)


@router.get("/{exp_id}", response_model=ExperimentOut)
def get_experiment(exp_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _out(_get(db, exp_id))


@router.delete("/{exp_id}", status_code=204)
def delete_experiment(exp_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(Role.researcher))):
    exp = _get(db, exp_id)
    if user.role != Role.admin and exp.owner_id != user.id:
        raise HTTPException(403, "Only the owner or an admin can delete this experiment")
    if any(r.status in (RunStatus.queued, RunStatus.scheduled, RunStatus.running) for r in exp.runs):
        raise HTTPException(409, "Cancel active runs first")
    db.delete(exp)
    db.commit()


@router.get("/{exp_id}/runs", response_model=list[RunOut])
def experiment_runs(exp_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _get(db, exp_id)
    return db.scalars(select(Run).where(Run.experiment_id == exp_id).order_by(Run.id.desc())).all()


@router.post("/{exp_id}/runs", response_model=RunOut, status_code=201)
def launch_run(exp_id: int, body: RunCreate, db: Session = Depends(get_db),
               user: User = Depends(require_role(Role.researcher))):
    exp = _get(db, exp_id)
    run = services.submit_run(db, exp, user, config=body.config, name=body.name, priority=body.priority,
                              resources=body.resources, max_retries=body.max_retries)
    db.commit()
    services.enqueue_after_commit([run])
    return run


@router.post("/{exp_id}/sweeps", response_model=list[RunOut], status_code=201)
def launch_sweep(exp_id: int, body: SweepCreate, db: Session = Depends(get_db),
                 user: User = Depends(require_role(Role.researcher))):
    exp = _get(db, exp_id)
    try:
        runs = services.submit_sweep(db, exp, user, grid=body.grid, base=body.base, priority=body.priority,
                                     resources=body.resources, max_runs=body.max_runs)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    services.enqueue_after_commit(runs)
    return runs


@router.post("/{exp_id}/analyze", response_model=AnalysisOut, status_code=201)
def analyze_experiment(exp_id: int, body: AnalyzeIn, db: Session = Depends(get_db),
                       user: User = Depends(require_role(Role.researcher))):
    exp = _get(db, exp_id)
    q = select(Run).where(Run.experiment_id == exp_id).options(selectinload(Run.metrics))
    if body.run_ids:
        q = q.where(Run.id.in_(body.run_ids))
    runs = [r for r in db.scalars(q).all() if r.status not in (RunStatus.queued,)]
    if not runs:
        raise HTTPException(422, "No started runs to analyse yet")
    report = analyze(exp, runs)
    a = Analysis(experiment_id=exp.id, run_ids=[r.id for r in runs], source=report["source"], model=report.get("model"),
                 summary=report["summary"], best_run_id=report.get("best_run_id"), anomalies=report["anomalies"],
                 recommendations=report["recommendations"], created_by_id=user.id)
    db.add(a)
    db.commit()
    return a


@router.get("/{exp_id}/analyses", response_model=list[AnalysisOut])
def list_analyses(exp_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Analysis).where(Analysis.experiment_id == exp_id).order_by(Analysis.id.desc()).limit(20)).all()
