from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..analyst import _claude_enabled
from ..auth import current_user
from ..config import get_settings
from ..db import get_db
from ..job_queue import get_queue
from ..models import ACTIVE, Experiment, Run, RunStatus, User, utcnow

router = APIRouter(tags=["system"])


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"db": True, "queue": get_queue().ping()}


@router.get("/api/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = get_settings()
    counts = {st.value: n for st, n in db.execute(select(Run.status, func.count()).group_by(Run.status)).all()}
    since = utcnow() - timedelta(hours=24)
    finished_24h = dict(db.execute(
        select(Run.status, func.count()).where(Run.finished_at >= since).group_by(Run.status)).all())
    ok = finished_24h.get(RunStatus.succeeded, 0)
    bad = finished_24h.get(RunStatus.failed, 0) + finished_24h.get(RunStatus.stalled, 0)
    q = get_queue()
    return {
        "runs_by_status": counts,
        "experiments": db.scalar(select(func.count()).select_from(Experiment)),
        "active": sum(counts.get(x.value, 0) for x in ACTIVE),
        "capacity": s.max_concurrent_runs,
        "queue_depth": q.depth(),
        "queue_head": q.peek(10),
        "success_rate_24h": round(ok / (ok + bad), 3) if ok + bad else None,
        "executor": s.executor,
        "analyst": "claude" if _claude_enabled() else "heuristic",
    }
