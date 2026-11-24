import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="mlops-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "QUEUE_URL": "memory://",
    "ARTIFACT_DIR": f"{_tmp}/artifacts",
    "LOG_DIR": f"{_tmp}/logs",
    "EXECUTOR": "local",
    "EMBEDDED_WORKER": "true",
    "DISPATCH_INTERVAL_S": "0.2",
    "STALL_TIMEOUT_S": "3",
    "MAX_CONCURRENT_RUNS": "3",
    "ANALYST_MODE": "heuristic",
    "CALLBACK_URL": "http://127.0.0.1:8765",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(client, email, pw):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin@mlops.local", "admin123")


@pytest.fixture(scope="session")
def researcher(client):
    return _login(client, "researcher@mlops.local", "research123")


@pytest.fixture(scope="session")
def viewer(client):
    return _login(client, "viewer@mlops.local", "viewer123")
