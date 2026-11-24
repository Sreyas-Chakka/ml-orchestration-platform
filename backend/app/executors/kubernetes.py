"""Dispatches each run as a Kubernetes batch/v1 Job (one pod per attempt).

Retries are owned by the platform (backoffLimit=0) so every attempt is visible as its own
event and the retry policy is identical across executors.
"""
from __future__ import annotations

import json
import re

from ..config import get_settings
from .base import ExecState, LaunchSpec

# Pod waiting reasons that will never resolve on their own.
FATAL_WAIT_REASONS = {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError"}


def _k8s_name(s: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", s.lower())[:63].strip("-")


class KubernetesExecutor:
    name = "kubernetes"

    def __init__(self):
        from kubernetes import client, config

        s = get_settings()
        if s.k8s_in_cluster:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.batch = client.BatchV1Api()
        self.core = client.CoreV1Api()
        self.client = client
        self.ns = s.k8s_namespace

    def _job_manifest(self, spec: LaunchSpec, name: str):
        c, s = self.client, get_settings()
        env = {**spec.env, "MLOPS_CONFIG": json.dumps(spec.config), "MLOPS_ENTRYPOINT": spec.entrypoint,
               "MLOPS_ARTIFACT_DIR": "/artifacts", "PYTHONUNBUFFERED": "1"}
        res = spec.resources or {}
        requests = {"cpu": res.get("cpu", "250m"), "memory": res.get("memory", "256Mi")}
        limits = {"cpu": res.get("cpu_limit", res.get("cpu", "1")), "memory": res.get("memory_limit", res.get("memory", "1Gi"))}
        if res.get("gpu"):
            limits["nvidia.com/gpu"] = str(res["gpu"])
        labels = {"app.kubernetes.io/name": "mlops-trainer", "mlops/run-id": str(spec.run_id),
                  "mlops/attempt": str(spec.attempt)}
        container = c.V1Container(
            name="trainer",
            image=s.k8s_trainer_image,
            image_pull_policy=s.k8s_image_pull_policy,
            env=[c.V1EnvVar(name=k, value=str(v)) for k, v in env.items()],
            resources=c.V1ResourceRequirements(requests=requests, limits=limits),
            volume_mounts=[c.V1VolumeMount(name="artifacts", mount_path="/artifacts")],
            security_context=c.V1SecurityContext(run_as_non_root=True, run_as_user=1000, allow_privilege_escalation=False),
        )
        pod = c.V1PodSpec(
            restart_policy="Never",
            containers=[container],
            volumes=[c.V1Volume(name="artifacts", persistent_volume_claim=c.V1PersistentVolumeClaimVolumeSource(
                claim_name=s.k8s_artifact_pvc))],
        )
        return c.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=c.V1ObjectMeta(name=name, labels=labels),
            spec=c.V1JobSpec(
                backoff_limit=0,
                ttl_seconds_after_finished=3600,
                active_deadline_seconds=int(res.get("timeout_s", 6 * 3600)),
                template=c.V1PodTemplateSpec(metadata=c.V1ObjectMeta(labels=labels), spec=pod),
            ),
        )

    def launch(self, spec: LaunchSpec) -> str:
        name = _k8s_name(f"mlops-run-{spec.run_id}-a{spec.attempt}")
        self.batch.create_namespaced_job(self.ns, self._job_manifest(spec, name))
        return name

    def _pods(self, job_name: str):
        return self.core.list_namespaced_pod(self.ns, label_selector=f"job-name={job_name}").items

    def poll(self, ref: str) -> ExecState:
        from kubernetes.client.exceptions import ApiException

        try:
            job = self.batch.read_namespaced_job_status(ref, self.ns)
        except ApiException as e:
            if e.status == 404:
                return ExecState("missing", message="job not found")
            raise
        st = job.status
        if st.succeeded:
            return ExecState("succeeded", exit_code=0)
        if st.failed:
            reason = next((cond.message or cond.reason for cond in (st.conditions or []) if cond.type == "Failed"), "")
            return ExecState("failed", message=f"job failed: {reason}".strip())
        for pod in self._pods(ref):
            for cs in pod.status.container_statuses or []:
                w = cs.state.waiting if cs.state else None
                if w and w.reason in FATAL_WAIT_REASONS:
                    return ExecState("failed", message=f"{w.reason}: {w.message or ''}".strip())
            if pod.status.phase == "Running":
                return ExecState("running")
        return ExecState("pending")

    def cancel(self, ref: str) -> None:
        from kubernetes.client.exceptions import ApiException

        try:
            self.batch.delete_namespaced_job(ref, self.ns, propagation_policy="Foreground")
        except ApiException as e:
            if e.status != 404:
                raise

    def logs(self, ref: str, tail: int = 500) -> str:
        pods = self._pods(ref)
        if not pods:
            return ""
        try:
            return self.core.read_namespaced_pod_log(pods[0].metadata.name, self.ns, tail_lines=tail)
        except Exception as e:  # pod still creating, etc.
            return f"[logs unavailable: {e}]"
