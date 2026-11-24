import pytest

from app.job_queue import MemoryQueue
from app.models import RunStatus
from app.services import TRANSITIONS, expand_grid


def test_queue_orders_by_priority_then_fifo():
    q = MemoryQueue()
    q.enqueue(1, 0)
    q.enqueue(2, 5)
    q.enqueue(3, 0)
    q.enqueue(4, 5)
    assert [q.pop("w") for _ in range(4)] == [2, 4, 1, 3]
    assert q.pop("w") is None


def test_queue_remove_and_dedupe():
    q = MemoryQueue()
    q.enqueue(1)
    q.enqueue(1)  # duplicate ignored
    q.enqueue(2)
    assert q.depth() == 2
    assert q.remove(1)
    assert q.pop("w") == 2
    assert q.pop("w") is None


def test_expand_grid():
    combos = expand_grid({"lr": [0.1, 0.01], "hidden": [8, 16, 32]}, max_runs=10)
    assert len(combos) == 6
    assert {"hidden": 8, "lr": 0.1} in combos
    with pytest.raises(ValueError):
        expand_grid({"a": list(range(5)), "b": list(range(5))}, max_runs=10)


def test_terminal_states_cannot_go_back_to_running():
    for st in (RunStatus.succeeded, RunStatus.failed, RunStatus.stalled, RunStatus.cancelled):
        assert RunStatus.running not in TRANSITIONS[st]


def test_kubernetes_job_manifest():
    from kubernetes import client

    from app.executors.base import LaunchSpec
    from app.executors.kubernetes import KubernetesExecutor

    ex = object.__new__(KubernetesExecutor)  # skip kubeconfig loading
    ex.client = client
    spec = LaunchSpec(run_id=7, entrypoint="mlp_classifier", config={"lr": 0.1},
                      resources={"cpu": "500m", "memory": "512Mi", "gpu": 1}, env={"MLOPS_RUN_ID": "7"}, attempt=1)
    job = client.ApiClient().sanitize_for_serialization(ex._job_manifest(spec, "mlops-run-7-a1"))
    pod = job["spec"]["template"]["spec"]
    c = pod["containers"][0]
    env = {e["name"]: e["value"] for e in c["env"]}
    assert job["spec"]["backoffLimit"] == 0 and pod["restartPolicy"] == "Never"
    assert env["MLOPS_ARTIFACT_DIR"] == "/artifacts" and env["MLOPS_CONFIG"] == '{"lr": 0.1}'
    assert c["resources"]["requests"] == {"cpu": "500m", "memory": "512Mi"}
    assert c["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert c["securityContext"]["runAsNonRoot"] is True
    assert job["metadata"]["labels"]["mlops/run-id"] == "7"
