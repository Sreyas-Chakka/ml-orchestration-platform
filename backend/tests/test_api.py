"""End-to-end: real dispatcher + local executor + real trainer subprocesses.

The trainer reports back over HTTP, so a uvicorn server is started on CALLBACK_URL's port
sharing the same database as the TestClient app.
"""
import threading
import time

import pytest
import uvicorn

TERMINAL = {"succeeded", "failed", "stalled", "cancelled"}
FAST = {"epochs": 4, "epoch_sleep_s": 0.05, "n_samples": 400}


@pytest.fixture(scope="module", autouse=True)
def callback_server(client):
    from app.main import app

    # Callback server shares the DB; the TestClient's lifespan already runs the dispatcher.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning", lifespan="off"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield
    server.should_exit = True


def wait_for(client, headers, run_id, statuses=TERMINAL, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in statuses:
            return run
        time.sleep(0.3)
    raise AssertionError(f"run {run_id} stuck in {run['status']}")


@pytest.fixture(scope="module")
def experiment(client, researcher):
    r = client.post("/api/experiments", headers=researcher,
                    json={"name": "spirals", "base_config": FAST, "primary_metric": "val_accuracy"})
    assert r.status_code == 201, r.text
    return r.json()


def test_auth_required(client):
    assert client.get("/api/experiments").status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@mlops.local", "password": "nope"}).status_code == 401


def test_viewer_cannot_write(client, viewer, experiment):
    assert client.get("/api/experiments", headers=viewer).status_code == 200
    assert client.post("/api/experiments", headers=viewer, json={"name": "x"}).status_code == 403
    assert client.post(f"/api/experiments/{experiment['id']}/runs", headers=viewer, json={}).status_code == 403


def test_only_admin_manages_users(client, admin, researcher):
    assert client.get("/api/auth/users", headers=researcher).status_code == 403
    assert len(client.get("/api/auth/users", headers=admin).json()) >= 3


def test_user_token_cannot_call_trainer_callbacks(client, researcher, experiment):
    r = client.post("/api/internal/runs/1/heartbeat", headers=researcher)
    assert r.status_code == 403


def test_run_succeeds_with_metrics_and_artifacts(client, researcher, experiment):
    r = client.post(f"/api/experiments/{experiment['id']}/runs", headers=researcher,
                    json={"config": {"learning_rate": 0.1}})
    assert r.status_code == 201
    run = wait_for(client, researcher, r.json()["id"])
    assert run["status"] == "succeeded", run
    assert run["progress"] == 1.0
    assert "val_accuracy" in run["summary"]
    metrics = client.get(f"/api/runs/{run['id']}/metrics", headers=researcher).json()
    assert len(metrics["val_accuracy"]) == FAST["epochs"]
    arts = client.get(f"/api/runs/{run['id']}/artifacts", headers=researcher).json()
    assert {a["name"] for a in arts} == {"model.npz", "model_card.json"}
    dl = client.get(f"/api/runs/{run['id']}/artifacts/{arts[0]['id']}/download", headers=researcher)
    assert dl.status_code == 200 and len(dl.content) == arts[0]["size_bytes"]
    assert "epoch" in client.get(f"/api/runs/{run['id']}/logs", headers=researcher).text


def test_failed_run_is_retried_then_fails(client, researcher, experiment):
    r = client.post(f"/api/experiments/{experiment['id']}/runs", headers=researcher,
                    json={"config": {"fail_at_epoch": 2}, "max_retries": 1})
    run = wait_for(client, researcher, r.json()["id"], statuses={"failed"}, timeout=60)
    assert run["attempt"] == 1  # original + one retry
    assert "injected failure" in run["error"]
    kinds = [e["kind"] for e in client.get(f"/api/runs/{run['id']}/events", headers=researcher).json()]
    assert "retry" in kinds


def test_hung_run_is_marked_stalled(client, researcher, experiment):
    r = client.post(f"/api/experiments/{experiment['id']}/runs", headers=researcher,
                    json={"config": {"hang_at_epoch": 2, "epochs": 50}})
    run = wait_for(client, researcher, r.json()["id"], timeout=60)
    assert run["status"] == "stalled", run
    assert "no heartbeat" in run["error"]


def test_cancel_queued_and_running(client, researcher, experiment):
    r = client.post(f"/api/experiments/{experiment['id']}/runs", headers=researcher,
                    json={"config": {"epochs": 200, "epoch_sleep_s": 0.2}})
    rid = r.json()["id"]
    wait_for(client, researcher, rid, statuses={"running"})
    c = client.post(f"/api/runs/{rid}/cancel", headers=researcher)
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    # retry of a cancelled run requeues it, and a second cancel while queued works too
    assert client.post(f"/api/runs/{rid}/retry", headers=researcher).json()["status"] == "queued"
    client.post(f"/api/runs/{rid}/cancel", headers=researcher)
    assert wait_for(client, researcher, rid)["status"] == "cancelled"


def test_sweep_compare_and_analyze(client, researcher, experiment):
    r = client.post(f"/api/experiments/{experiment['id']}/sweeps", headers=researcher,
                    json={"grid": {"learning_rate": [0.01, 0.3], "hidden_units": [4, 32]}})
    assert r.status_code == 201
    ids = [x["id"] for x in r.json()]
    assert len(ids) == 4 and len({x["sweep_id"] for x in r.json()}) == 1
    for rid in ids:
        assert wait_for(client, researcher, rid, timeout=60)["status"] == "succeeded"

    cmp = client.get("/api/runs/compare", params={"ids": ",".join(map(str, ids))}, headers=researcher).json()
    assert set(cmp["differing_config_keys"]) == {"learning_rate", "hidden_units"}
    assert "val_accuracy" in cmp["metric_keys"]

    a = client.post(f"/api/experiments/{experiment['id']}/analyze", headers=researcher, json={"run_ids": ids})
    assert a.status_code == 201, a.text
    body = a.json()
    assert body["source"] == "heuristic"
    assert body["best_run_id"] in ids
    assert body["summary"]

    exp = client.get(f"/api/experiments/{experiment['id']}", headers=researcher).json()
    assert exp["best_run_id"] is not None


def test_stats_and_prometheus(client, researcher):
    s = client.get("/api/stats", headers=researcher).json()
    assert s["runs_by_status"]["succeeded"] >= 5
    text = client.get("/metrics").text
    assert "mlops_runs_finished_total" in text and "mlops_stall_detections_total" in text
