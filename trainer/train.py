"""Containerised training job launched by the platform (one process / pod per run).

Contract with the platform (all via environment variables):
  MLOPS_API_URL, MLOPS_RUN_ID, MLOPS_RUN_TOKEN  - where/how to report back
  MLOPS_CONFIG      - JSON hyperparameters
  MLOPS_ENTRYPOINT  - which model to train (mlp_classifier | logistic_regression)
  MLOPS_ARTIFACT_DIR - where to write model files (a shared PVC in Kubernetes)

The job reports status, per-epoch metrics and artifacts, and sends heartbeats from a
background thread so the platform's watchdog can tell "slow" from "hung".
Only depends on numpy + the standard library to keep the image small.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

API = os.environ.get("MLOPS_API_URL", "").rstrip("/")
RUN_ID = os.environ.get("MLOPS_RUN_ID", "local")
TOKEN = os.environ.get("MLOPS_RUN_TOKEN", "")
CONFIG = json.loads(os.environ.get("MLOPS_CONFIG", "{}"))
ENTRYPOINT = os.environ.get("MLOPS_ENTRYPOINT", "mlp_classifier")
ARTIFACT_DIR = Path(os.environ.get("MLOPS_ARTIFACT_DIR", "./artifacts"))

DEFAULTS = {
    "learning_rate": 0.05,
    "epochs": 30,
    "hidden_units": 32,
    "batch_size": 64,
    "weight_decay": 0.0,
    "n_samples": 2000,
    "noise": 0.25,
    "seed": 0,
    "epoch_sleep_s": 0.3,  # simulate heavier work so the dashboard has something to watch
    "fail_at_epoch": None,  # inject a crash (for testing retries / alerts)
    "hang_at_epoch": None,  # inject a hang (for testing stall detection)
}


class Stop(Exception):
    """The platform told us to stop (run cancelled or marked stalled)."""


# --------------------------------------------------------------------------- platform client
def call(path: str, body: dict, retries: int = 3):
    if not API:
        return None
    req = urllib.request.Request(
        f"{API}/api/internal/runs/{RUN_ID}/{path}",
        data=json.dumps(body, allow_nan=True).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 409:
                raise Stop(e.read().decode(errors="replace"))
            if e.code < 500 or i == retries - 1:
                print(f"[mlops] {path} -> HTTP {e.code}: {e.read()[:200]!r}", file=sys.stderr)
                return None
        except (urllib.error.URLError, TimeoutError) as e:
            if i == retries - 1:
                print(f"[mlops] {path} unreachable: {e}", file=sys.stderr)
                return None
        time.sleep(0.5 * 2**i)


class Heartbeat(threading.Thread):
    def __init__(self, every_s: float = 5.0):
        super().__init__(daemon=True)
        self.every_s, self.stopped, self.paused = every_s, threading.Event(), threading.Event()
        self.cancelled = threading.Event()

    def run(self):
        while not self.stopped.wait(self.every_s):
            if self.paused.is_set():
                continue
            try:
                call("heartbeat", {})
            except Stop:
                self.cancelled.set()
                return


# --------------------------------------------------------------------------- data + model
def make_data(n: int, noise: float, rng: np.random.Generator):
    """Two interleaved spirals: non-linear, so hidden_units and learning_rate genuinely matter."""
    k = n // 2
    t = np.sqrt(rng.uniform(0, 1, k)) * 3 * np.pi
    a = np.stack([t * np.cos(t), t * np.sin(t)], 1) / (3 * np.pi)
    b = -a
    X = np.vstack([a, b]) + rng.normal(0, noise / 4, (2 * k, 2))
    y = np.concatenate([np.zeros(k), np.ones(k)])
    idx = rng.permutation(2 * k)
    X, y = X[idx], y[idx]
    split = int(0.8 * len(X))
    return X[:split], y[:split], X[split:], y[split:]


def init_params(hidden: int, rng):
    if hidden <= 0:  # logistic regression
        return {"W": rng.normal(0, 0.5, (2, 1)), "b": np.zeros(1)}
    return {
        "W1": rng.normal(0, np.sqrt(2 / 2), (2, hidden)), "b1": np.zeros(hidden),
        "W2": rng.normal(0, np.sqrt(2 / hidden), (hidden, hidden)), "b2": np.zeros(hidden),
        "W3": rng.normal(0, np.sqrt(1 / hidden), (hidden, 1)), "b3": np.zeros(1),
    }


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -60, 60)))


def forward(p, X):
    if "W" in p:
        return sigmoid(X @ p["W"] + p["b"]).ravel(), None
    h1 = np.maximum(0, X @ p["W1"] + p["b1"])
    h2 = np.maximum(0, h1 @ p["W2"] + p["b2"])
    return sigmoid(h2 @ p["W3"] + p["b3"]).ravel(), (h1, h2)


def loss_acc(p, X, y):
    with np.errstate(all="ignore"):
        prob, _ = forward(p, X)
        eps = 1e-9
        loss = float(-np.mean(y * np.log(prob + eps) + (1 - y) * np.log(1 - prob + eps)))
    acc = float(np.mean((prob > 0.5) == y))
    return loss, acc


def sgd_step(p, X, y, lr, wd):
    prob, cache = forward(p, X)
    d = ((prob - y) / len(y))[:, None]
    if cache is None:
        grads = {"W": X.T @ d, "b": d.sum(0)}
    else:
        h1, h2 = cache
        grads = {"W3": h2.T @ d, "b3": d.sum(0)}
        dh2 = (d @ p["W3"].T) * (h2 > 0)
        grads.update({"W2": h1.T @ dh2, "b2": dh2.sum(0)})
        dh1 = (dh2 @ p["W2"].T) * (h1 > 0)
        grads.update({"W1": X.T @ dh1, "b1": dh1.sum(0)})
    for k, g in grads.items():
        if k.startswith("W"):
            g = g + wd * p[k]
        p[k] -= lr * g


# --------------------------------------------------------------------------- main
def train(cfg: dict, hb: Heartbeat) -> dict:
    rng = np.random.default_rng(int(cfg["seed"]))
    Xtr, ytr, Xva, yva = make_data(int(cfg["n_samples"]), float(cfg["noise"]), rng)
    hidden = 0 if ENTRYPOINT == "logistic_regression" else int(cfg["hidden_units"])
    p = init_params(hidden, rng)
    lr, wd, bs, epochs = float(cfg["learning_rate"]), float(cfg["weight_decay"]), int(cfg["batch_size"]), int(cfg["epochs"])
    print(f"[train] run={RUN_ID} entrypoint={ENTRYPOINT} train={len(Xtr)} val={len(Xva)} cfg={cfg}", flush=True)

    best = {"val_accuracy": -1.0}
    for epoch in range(1, epochs + 1):
        if hb.cancelled.is_set():
            raise Stop("cancelled")
        if cfg.get("fail_at_epoch") and epoch == int(cfg["fail_at_epoch"]):
            raise RuntimeError(f"injected failure at epoch {epoch} (fail_at_epoch)")
        if cfg.get("hang_at_epoch") and epoch == int(cfg["hang_at_epoch"]):
            print(f"[train] simulating a hang at epoch {epoch}", flush=True)
            hb.paused.set()  # a real deadlock would also stop heartbeats
            time.sleep(10**6)

        perm = rng.permutation(len(Xtr))
        with np.errstate(all="ignore"):
            for i in range(0, len(Xtr), bs):
                b = perm[i:i + bs]
                sgd_step(p, Xtr[b], ytr[b], lr, wd)
        tl, ta = loss_acc(p, Xtr, ytr)
        vl, va = loss_acc(p, Xva, yva)
        print(f"[train] epoch {epoch:3d}/{epochs} train_loss={tl:.4f} train_acc={ta:.4f} val_loss={vl:.4f} val_acc={va:.4f}",
              flush=True)
        call("metrics", {"points": [{"step": epoch, "values": {"train_loss": tl, "train_accuracy": ta,
                                                               "val_loss": vl, "val_accuracy": va}}],
                         "progress": epoch / epochs})
        if va > best["val_accuracy"]:
            best = {"val_accuracy": va, "val_loss": vl, "best_epoch": epoch}
        if math.isnan(tl):
            print("[train] loss is NaN — continuing so the platform records the divergence", flush=True)
        time.sleep(float(cfg["epoch_sleep_s"]))

    # ---- artifacts ----
    out_dir = ARTIFACT_DIR / f"run-{RUN_ID}"
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.npz"
    np.savez(model_path, **p)
    card = {"run_id": RUN_ID, "entrypoint": ENTRYPOINT, "config": cfg, "final": {"train_loss": tl, "train_accuracy": ta,
            "val_loss": vl, "val_accuracy": va}, "best": best}
    card_path = out_dir / "model_card.json"
    card_path.write_text(json.dumps(card, indent=2, default=str))
    for path, kind in ((model_path, "model"), (card_path, "metadata")):
        data = path.read_bytes()
        call("artifacts", {"name": path.name, "kind": kind, "uri": f"run-{RUN_ID}/{path.name}",
                           "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                           "meta": {"format": path.suffix.lstrip(".")}})
    summary = {"train_loss": tl, "train_accuracy": ta, "val_loss": vl, "val_accuracy": va,
               "best_val_accuracy": best["val_accuracy"], "best_epoch": best.get("best_epoch", 0)}
    return {k: v for k, v in summary.items() if isinstance(v, (int, float)) and math.isfinite(v)}


def main() -> int:
    cfg = {**DEFAULTS, **CONFIG}
    hb = Heartbeat()
    try:
        call("status", {"status": "running"})
        hb.start()
        summary = train(cfg, hb)
        hb.stopped.set()
        call("status", {"status": "succeeded", "summary": summary})
        print("[train] done", flush=True)
        return 0
    except Stop as e:
        print(f"[train] stopping on platform request: {e}", flush=True)
        return 0
    except Exception as e:
        hb.stopped.set()
        traceback.print_exc()
        try:
            call("status", {"status": "failed", "error": f"{type(e).__name__}: {e}"})
        except Stop:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
