"""Standalone dispatcher process: `python -m app.worker`.

Used in docker-compose / Kubernetes so the scheduler scales and restarts independently of the
API. Exposes its own Prometheus endpoint on WORKER_METRICS_PORT (default 9100).
"""
import logging
import os
import signal
import threading

from prometheus_client import start_http_server

from .auth import ensure_bootstrap_users
from .db import SessionLocal, init_db
from .dispatcher import Dispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    init_db()
    with SessionLocal() as db:
        ensure_bootstrap_users(db)
    start_http_server(int(os.environ.get("WORKER_METRICS_PORT", "9100")))
    d = Dispatcher()
    d.recover()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    t = threading.Thread(target=d.loop, daemon=True)
    t.start()
    stop.wait()
    d.stop()


if __name__ == "__main__":
    main()
