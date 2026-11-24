"""Experiment analyst.

Two layers:
  1. Deterministic detectors compute per-run facts and flag anomalies (NaN/diverging loss,
     overfitting gap, plateaus, stalls, crashes, unusually slow runs). These always run.
  2. If Claude is configured, the facts + detector output are sent to the model, which writes
     the narrative summary, picks the best run, and adds/rewrites recommendations. Its output is
     constrained to a JSON schema. If the call fails, the heuristic report is stored instead.
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
from collections import defaultdict
from typing import Any

from . import monitoring as m
from .config import get_settings
from .models import Experiment, Run, RunStatus

log = logging.getLogger("mlops.analyst")


# --------------------------------------------------------------------------- facts
def _series(run: Run) -> dict[str, list[tuple[int, float]]]:
    out: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for p in run.metrics:
        out[p.key].append((p.step, p.value))
    return out


def _final(series: dict, key: str) -> float | None:
    s = series.get(key)
    return s[-1][1] if s else None


def _best(values: list[float], goal: str) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return None
    return max(vals) if goal == "max" else min(vals)


def run_facts(run: Run, exp: Experiment) -> dict[str, Any]:
    series = _series(run)
    pm = exp.primary_metric
    primary_vals = [v for _, v in series.get(pm, [])]
    return {
        "run_id": run.id,
        "name": run.name,
        "status": run.status.value,
        "attempt": run.attempt,
        "config": run.config,
        "duration_s": round(run.duration_s, 1) if run.duration_s else None,
        "error": run.error,
        "steps_logged": max((s for pts in series.values() for s, _ in pts), default=0),
        "final": {k: round(v[-1][1], 5) for k, v in series.items() if v},
        f"best_{pm}": _best(primary_vals, exp.metric_goal),
    }


# --------------------------------------------------------------------------- detectors
def detect(run: Run, exp: Experiment, peer_durations: list[float]) -> list[dict[str, Any]]:
    s = _series(run)
    flags: list[dict[str, Any]] = []

    def flag(severity: str, issue: str, recommendation: str):
        flags.append({"run_id": run.id, "severity": severity, "issue": issue, "recommendation": recommendation})

    if run.status == RunStatus.failed:
        flag("high", f"Run failed: {(run.error or 'unknown error')[:200]}",
             "Check the run logs; if it is a transient infra error enable retries (max_retries).")
    if run.status == RunStatus.stalled:
        flag("high", "Run stopped sending heartbeats and was killed by the watchdog.",
             "Look for deadlocks / data-loader hangs, or raise STALL_TIMEOUT for long uninstrumented phases.")

    loss = [v for _, v in s.get("train_loss", [])]
    if any(math.isnan(v) or math.isinf(v) for v in loss):
        flag("high", "Training loss became NaN/Inf.", "Lower the learning rate, add gradient clipping, check inputs for NaNs.")
    elif len(loss) >= 4:
        first, last = loss[0], loss[-1]
        if last > first * 1.5:
            flag("high", f"Training loss diverged ({first:.3f} → {last:.3f}).", "Reduce learning_rate (try ÷3–÷10).")
        tail = loss[-max(3, len(loss) // 4):]
        if len(tail) >= 3 and first > 0 and abs(tail[0] - tail[-1]) / max(abs(tail[0]), 1e-9) < 0.005 and last > 0.5 * first:
            flag("medium", "Loss plateaued early at a high value.", "Increase capacity or learning rate, or check label quality.")

    tr, va = _final(s, "train_accuracy"), _final(s, "val_accuracy")
    if tr is not None and va is not None and tr - va > 0.08:
        flag("medium", f"Overfitting: train acc {tr:.3f} vs val acc {va:.3f} (gap {tr - va:.3f}).",
             "Add regularization (weight_decay / dropout), more data, or early stopping.")
    vl = [v for _, v in s.get("val_loss", [])]
    if len(vl) >= 5:
        best_i = min(range(len(vl)), key=vl.__getitem__)
        if best_i < len(vl) - 3 and vl[-1] > vl[best_i] * 1.1:
            flag("medium", f"Validation loss bottomed out at step {best_i + 1} and rose {vl[-1] / vl[best_i] - 1:.0%} after.",
                 "Use early stopping / checkpoint the best epoch; fewer epochs would save compute.")

    if run.duration_s and len(peer_durations) >= 3 and run.status == RunStatus.succeeded:
        med = statistics.median(peer_durations)
        if med > 0 and run.duration_s > 2.5 * med:
            flag("low", f"Run took {run.duration_s:.0f}s, {run.duration_s / med:.1f}× the median of its peers.",
                 "Check node contention or resource requests for this run.")
    return flags


def heuristic_report(exp: Experiment, runs: list[Run]) -> dict[str, Any]:
    durations = [r.duration_s for r in runs if r.duration_s and r.status == RunStatus.succeeded]
    facts = [run_facts(r, exp) for r in runs]
    anomalies = [a for r in runs for a in detect(r, exp, durations)]
    key = f"best_{exp.primary_metric}"
    scored = [f for f in facts if f[key] is not None and f["status"] == "succeeded"]
    best = None
    if scored:
        best = (max if exp.metric_goal == "max" else min)(scored, key=lambda f: f[key])
    by_status = defaultdict(int)
    for f in facts:
        by_status[f["status"]] += 1
    parts = [f"{len(runs)} runs analysed ({', '.join(f'{n} {k}' for k, n in sorted(by_status.items()))})."]
    if best:
        cfg = ", ".join(f"{k}={v}" for k, v in best["config"].items())
        parts.append(f"Best run is #{best['run_id']} with {exp.primary_metric}={best[key]:.4f} ({cfg}).")
    if anomalies:
        hi = sum(a["severity"] == "high" for a in anomalies)
        parts.append(f"{len(anomalies)} anomalies flagged ({hi} high severity).")
    recs = []
    if best and len(scored) >= 3:
        recs.append(f"Narrow the next sweep around run #{best['run_id']}'s configuration.")
    recs += sorted({a["recommendation"] for a in anomalies if a["severity"] == "high"})
    return {"summary": " ".join(parts), "best_run_id": best["run_id"] if best else None,
            "anomalies": anomalies, "recommendations": recs[:6], "facts": facts}


# --------------------------------------------------------------------------- Claude
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "best_run_id": {"type": ["integer", "null"]},
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "issue": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
                "required": ["run_id", "severity", "issue", "recommendation"],
                "additionalProperties": False,
            },
        },
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "best_run_id", "anomalies", "recommendations"],
    "additionalProperties": False,
}

SYSTEM = """You are an ML experiment analyst embedded in a training-orchestration platform.
You receive one experiment's metadata, per-run facts (config, final metrics, status, duration,
errors) and anomalies already found by deterministic detectors.

Write for an ML engineer deciding what to run next:
- summary: 3-6 sentences. Which hyperparameters mattered and in which direction, which run is
  best and by how much, and anything that makes the comparison unreliable (failures, too few
  runs, metric noise). Cite run ids as #id. Only state effects the numbers support.
- best_run_id: the best succeeded run by the primary metric and goal, or null if none succeeded.
- anomalies: keep every detector finding that is real (you may reword it), and add any further
  problems you can see in the facts. Do not invent metrics that are not in the data.
- recommendations: 2-5 concrete next steps (specific configs to try, what to fix)."""


def _claude_enabled() -> bool:
    mode = get_settings().analyst_mode
    if mode == "heuristic":
        return False
    if mode == "claude":
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def claude_report(exp: Experiment, base: dict[str, Any]) -> dict[str, Any]:
    import anthropic

    payload = {
        "experiment": {"name": exp.name, "description": exp.description, "entrypoint": exp.entrypoint,
                       "primary_metric": exp.primary_metric, "goal": exp.metric_goal},
        "runs": base["facts"],
        "detector_anomalies": base["anomalies"],
    }
    client = anthropic.Anthropic()
    # Refusal fallbacks: on a policy decline the API re-runs the request on a fallback model.
    resp = client.beta.messages.create(
        model=get_settings().analyst_model,
        max_tokens=16000,
        system=SYSTEM,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("analysis truncated (max_tokens)")
    text = next(b.text for b in resp.content if b.type == "text")
    report = json.loads(text)
    report["model"] = resp.model
    return report


def analyze(exp: Experiment, runs: list[Run]) -> dict[str, Any]:
    base = heuristic_report(exp, runs)
    if runs and _claude_enabled():
        try:
            report = claude_report(exp, base)
            m.ANALYSES.labels("claude").inc()
            valid_ids = {r.id for r in runs}
            if report.get("best_run_id") not in valid_ids:
                report["best_run_id"] = base["best_run_id"]
            report["anomalies"] = [a for a in report["anomalies"] if a.get("run_id") in valid_ids]
            return {**report, "source": "claude"}
        except Exception as e:  # network, auth, refusal, schema... fall back, never fail the request
            log.warning("Claude analysis failed, using heuristic report: %s", e)
            base["summary"] += f" (LLM analysis unavailable: {type(e).__name__}; showing rule-based report.)"
    m.ANALYSES.labels("heuristic").inc()
    return {**base, "source": "heuristic", "model": None}
