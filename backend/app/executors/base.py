from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExecState:
    """What the executor knows about a launched job, independent of what the trainer reported."""

    phase: str  # pending | running | succeeded | failed | missing
    exit_code: int | None = None
    message: str = ""


@dataclass
class LaunchSpec:
    run_id: int
    entrypoint: str
    config: dict
    resources: dict
    env: dict[str, str]
    attempt: int


class Executor(Protocol):
    name: str

    def launch(self, spec: LaunchSpec) -> str:
        """Start the job and return an executor reference (pid, k8s job name, ...)."""

    def poll(self, ref: str) -> ExecState: ...

    def cancel(self, ref: str) -> None: ...

    def logs(self, ref: str, tail: int = 500) -> str: ...
