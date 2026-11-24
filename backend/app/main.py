import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from .auth import ensure_bootstrap_users
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import auth, experiments, internal, runs, system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_db()
    with SessionLocal() as db:
        ensure_bootstrap_users(db)
    dispatcher = None
    if s.embedded_worker:
        from .dispatcher import Dispatcher

        dispatcher = Dispatcher()
        dispatcher.start()
    yield
    if dispatcher:
        dispatcher.stop()


app = FastAPI(title="ML Experiment & Job Orchestration Platform", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (system.router, auth.router, experiments.router, runs.router, internal.router):
    app.include_router(r)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
