"""Runtime configuration, read from environment variables (or a .env file)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- storage -------------------------------------------------------------
    # Postgres in docker-compose / k8s; SQLite for zero-dependency local dev.
    database_url: str = f"sqlite:///{ROOT / '.data' / 'mlops.db'}"
    # "redis://host:6379/0" for the real queue; "memory://" for a single-process dev queue.
    queue_url: str = "memory://"
    artifact_dir: str = str(ROOT / ".data" / "artifacts")
    log_dir: str = str(ROOT / ".data" / "logs")

    # --- auth ----------------------------------------------------------------
    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    run_token_hours: int = 48
    bootstrap_admin_email: str = "admin@mlops.local"
    bootstrap_admin_password: str = "admin123"
    seed_demo_users: bool = True

    # --- scheduling ----------------------------------------------------------
    # "local" runs each training job as a subprocess; "kubernetes" creates a batch/v1 Job per run.
    executor: str = "local"
    max_concurrent_runs: int = 4
    embedded_worker: bool = True  # run the dispatcher inside the API process
    dispatch_interval_s: float = 1.0
    stall_timeout_s: int = 60  # no heartbeat for this long -> run is STALLED
    max_retries_default: int = 0

    # --- kubernetes executor -------------------------------------------------
    k8s_namespace: str = "mlops"
    k8s_trainer_image: str = "mlops-trainer:latest"
    k8s_image_pull_policy: str = "IfNotPresent"
    k8s_artifact_pvc: str = "mlops-artifacts"
    k8s_in_cluster: bool = False
    # URL the training pods use to call back into the API.
    callback_url: str = "http://127.0.0.1:8000"

    # --- LLM analyst ---------------------------------------------------------
    # "auto": use Claude when ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN is set, else heuristics only.
    analyst_mode: str = "auto"  # auto | claude | heuristic
    analyst_model: str = "claude-opus-5-5"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
