"""Priority job queue.

Redis implementation uses a sorted set (score = -priority, then FIFO by enqueue time) and
ZPOPMIN so multiple dispatcher replicas can pull jobs without double-dispatch. A "claimed"
hash records which dispatcher took a job so a crashed dispatcher's jobs can be requeued.

The in-memory implementation exists so the platform runs with zero infrastructure in dev.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time
from typing import Protocol

QUEUE_KEY = "mlops:queue"
CLAIMED_KEY = "mlops:claimed"


def _score(priority: int, ts: float) -> float:
    # Higher priority first; within a priority, earlier first. Timestamps fit in 1e10.
    return -priority * 1e10 + ts


class JobQueue(Protocol):
    def enqueue(self, run_id: int, priority: int = 0) -> None: ...
    def pop(self, worker_id: str) -> int | None: ...
    def ack(self, run_id: int) -> None: ...
    def remove(self, run_id: int) -> bool: ...
    def depth(self) -> int: ...
    def peek(self, limit: int = 50) -> list[int]: ...
    def ping(self) -> bool: ...
    def acquire_leader(self, worker_id: str, ttl_s: int = 10) -> bool: ...


class MemoryQueue:
    def __init__(self):
        self._heap: list[tuple[float, int, int]] = []
        self._removed: set[int] = set()
        self._queued: set[int] = set()
        self._counter = itertools.count()
        self._lock = threading.Lock()

    def enqueue(self, run_id: int, priority: int = 0) -> None:
        with self._lock:
            if run_id in self._queued:
                return
            self._removed.discard(run_id)
            self._queued.add(run_id)
            heapq.heappush(self._heap, (_score(priority, time.time()), next(self._counter), run_id))

    def pop(self, worker_id: str) -> int | None:
        with self._lock:
            while self._heap:
                _, _, run_id = heapq.heappop(self._heap)
                if run_id in self._removed:
                    self._removed.discard(run_id)
                    continue
                self._queued.discard(run_id)
                return run_id
            return None

    def ack(self, run_id: int) -> None:
        pass

    def remove(self, run_id: int) -> bool:
        with self._lock:
            if run_id in self._queued:
                self._queued.discard(run_id)
                self._removed.add(run_id)
                return True
            return False

    def depth(self) -> int:
        return len(self._queued)

    def peek(self, limit: int = 50) -> list[int]:
        with self._lock:
            return [r for _, _, r in sorted(self._heap) if r in self._queued][:limit]

    def ping(self) -> bool:
        return True

    def acquire_leader(self, worker_id: str, ttl_s: int = 10) -> bool:
        return True  # single process


class RedisQueue:
    def __init__(self, url: str):
        import redis

        self.r = redis.Redis.from_url(url, decode_responses=True)

    def enqueue(self, run_id: int, priority: int = 0) -> None:
        self.r.zadd(QUEUE_KEY, {str(run_id): _score(priority, time.time())}, nx=True)

    def pop(self, worker_id: str) -> int | None:
        res = self.r.zpopmin(QUEUE_KEY, 1)
        if not res:
            return None
        run_id = res[0][0]
        self.r.hset(CLAIMED_KEY, run_id, f"{worker_id}:{time.time()}")
        return int(run_id)

    def ack(self, run_id: int) -> None:
        self.r.hdel(CLAIMED_KEY, str(run_id))

    def remove(self, run_id: int) -> bool:
        return bool(self.r.zrem(QUEUE_KEY, str(run_id)))

    def depth(self) -> int:
        return int(self.r.zcard(QUEUE_KEY))

    def peek(self, limit: int = 50) -> list[int]:
        return [int(x) for x in self.r.zrange(QUEUE_KEY, 0, limit - 1)]

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:
            return False

    def acquire_leader(self, worker_id: str, ttl_s: int = 10) -> bool:
        """Only one dispatcher replica schedules at a time; others stand by as hot spares."""
        key = "mlops:dispatcher-leader"
        if self.r.set(key, worker_id, nx=True, ex=ttl_s):
            return True
        if self.r.get(key) == worker_id:
            self.r.expire(key, ttl_s)
            return True
        return False


_queue: JobQueue | None = None
_lock = threading.Lock()


def get_queue() -> JobQueue:
    global _queue
    with _lock:
        if _queue is None:
            from .config import get_settings

            url = get_settings().queue_url
            _queue = MemoryQueue() if url.startswith("memory") else RedisQueue(url)
        return _queue


def set_queue(q: JobQueue | None) -> None:
    global _queue
    _queue = q
