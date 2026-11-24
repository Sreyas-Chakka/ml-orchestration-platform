"""Runs each training job as a local subprocess. Used for dev and in CI."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from ..config import ROOT, get_settings
from .base import ExecState, LaunchSpec

TRAINER = ROOT / "trainer" / "train.py"


class LocalExecutor:
    name = "local"

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        Path(get_settings().log_dir).mkdir(parents=True, exist_ok=True)

    def _log_path(self, ref: str) -> Path:
        return Path(get_settings().log_dir) / f"{ref}.log"

    def launch(self, spec: LaunchSpec) -> str:
        ref = f"run-{spec.run_id}-a{spec.attempt}"
        env = {**os.environ, **spec.env, "PYTHONUNBUFFERED": "1"}
        env["MLOPS_CONFIG"] = json.dumps(spec.config)
        env["MLOPS_ENTRYPOINT"] = spec.entrypoint
        log = open(self._log_path(ref), "w")
        proc = subprocess.Popen(
            [sys.executable, str(TRAINER)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(ROOT),
            start_new_session=True,  # own process group so cancel kills children too
        )
        log.close()
        with self._lock:
            self._procs[ref] = proc
        return ref

    def poll(self, ref: str) -> ExecState:
        with self._lock:
            proc = self._procs.get(ref)
        if proc is None:
            # API restarted and lost the handle: the trainer's own status callback is authoritative.
            return ExecState("missing", message="process handle not found (API restart?)")
        code = proc.poll()
        if code is None:
            return ExecState("running")
        if code == 0:
            return ExecState("succeeded", exit_code=0)
        return ExecState("failed", exit_code=code, message=f"process exited with code {code}")

    def cancel(self, ref: str) -> None:
        with self._lock:
            proc = self._procs.get(ref)
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def logs(self, ref: str, tail: int = 500) -> str:
        p = self._log_path(ref)
        if not p.exists():
            return ""
        with open(p, errors="replace") as f:
            return "".join(deque(f, maxlen=tail))
