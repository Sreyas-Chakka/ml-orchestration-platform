"""Prometheus instrumentation. Scraped at GET /metrics.

Gauges that reflect DB state (runs by status, queue depth) are refreshed by the dispatcher
on every tick, so they are correct even with several API replicas behind a load balancer.
"""
from prometheus_client import Counter, Gauge, Histogram

RUNS_SUBMITTED = Counter("mlops_runs_submitted_total", "Runs submitted", ["experiment"])
RUNS_FINISHED = Counter("mlops_runs_finished_total", "Runs reaching a terminal state", ["status"])
RUNS_RETRIED = Counter("mlops_runs_retried_total", "Automatic retries of failed/stalled runs")
DISPATCH_ERRORS = Counter("mlops_dispatch_errors_total", "Errors launching runs on the executor")
STALL_DETECTIONS = Counter("mlops_stall_detections_total", "Runs marked stalled by the watchdog")

RUNS_BY_STATUS = Gauge("mlops_runs", "Runs currently in each status", ["status"])
QUEUE_DEPTH = Gauge("mlops_queue_depth", "Jobs waiting in the queue")
ACTIVE_RUNS = Gauge("mlops_active_runs", "Runs scheduled or running")
CAPACITY = Gauge("mlops_capacity", "Max concurrent runs")
OLDEST_HEARTBEAT_AGE = Gauge("mlops_oldest_heartbeat_age_seconds", "Age of the stalest heartbeat among running runs")
DISPATCHER_LAST_TICK = Gauge("mlops_dispatcher_last_tick_timestamp", "Unix time of the dispatcher's last loop")

RUN_DURATION = Histogram(
    "mlops_run_duration_seconds",
    "Wall-clock duration of finished runs",
    ["status"],
    buckets=(5, 15, 30, 60, 120, 300, 600, 1800, 3600, 7200),
)
QUEUE_WAIT = Histogram(
    "mlops_queue_wait_seconds", "Time from submission to dispatch", buckets=(0.5, 1, 2, 5, 10, 30, 60, 300, 900)
)
ANALYSES = Counter("mlops_analyses_total", "LLM analyst invocations", ["source"])
