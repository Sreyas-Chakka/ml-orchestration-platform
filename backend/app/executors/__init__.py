from __future__ import annotations

import threading

from ..config import get_settings
from .base import ExecState, Executor

_executors: dict[str, Executor] = {}
_lock = threading.Lock()


def get_executor(name: str | None = None) -> Executor:
    name = name or get_settings().executor
    with _lock:
        if name not in _executors:
            if name == "local":
                from .local import LocalExecutor

                _executors[name] = LocalExecutor()
            elif name == "kubernetes":
                from .kubernetes import KubernetesExecutor

                _executors[name] = KubernetesExecutor()
            else:
                raise ValueError(f"Unknown executor '{name}'")
        return _executors[name]


def register_executor(name: str, ex: Executor) -> None:
    _executors[name] = ex


__all__ = ["ExecState", "Executor", "get_executor", "register_executor"]
