"""All configuration comes from environment variables (or backend/.env).

Defaults suit development; the local Docker stack sets its values in docker-compose.local.yml and
self-hosted servers in backend/.env (see .env.example). Secrets never go in the repository.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # PostgreSQL with pgvector (TimescaleDB optional): the local `db` container, or Tiger Cloud.
    database_url: str = "postgresql://rescrub:rescrub@localhost:5432/rescrub"

    # Where videos live: "local" (a folder) or "s3" (any S3-compatible bucket, e.g. Vultr Object Storage).
    storage_backend: str = "local"
    local_storage_dir: Path = BACKEND_DIR / "data"
    s3_endpoint_url: str = ""  # e.g. https://ewr1.vultrobjects.com
    s3_region: str = "us-east-1"
    s3_bucket: str = "rescrub"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    presign_ttl_sec: int = 3600
    # Delete the uploaded original once the annotated video is saved.
    delete_original_after_processing: bool = False

    # Website origins allowed to call the API, comma separated.
    cors_origins: str = "http://localhost:3000"
    max_upload_mb: int = 500
    max_video_sec: float = 3600  # 60 minutes; MM-OR training evaluation uses its own limit (run_all.sh)
    uploads_per_hour_per_client: int = 10
    uploads_per_day_per_user: int = 20  # every upload uses worker time; 0 = no limit
    requests_per_minute_per_client: int = 120
    enable_api_docs: bool = False

    # Sign-in. Cookies are Secure (HTTPS only) unless COOKIE_SECURE=false for http:// development.
    cookie_secure: bool = True
    session_hours: int = 168  # 7 days, then sign in again
    logins_per_15min_per_email: int = 10
    logins_per_15min_per_ip: int = 60  # a whole class may share one school IP
    # Self-service sign-up on the website's "Create account" page. Off = accounts only from
    # `python -m rescrub.accounts`. REGISTRATION_EMAIL_DOMAINS (comma separated, e.g. school.edu)
    # limits sign-up to those addresses; empty = any address.
    allow_registration: bool = True
    registration_email_domains: str = ""
    registrations_per_hour_per_ip: int = 10
    # Sign-up checks that the email's domain receives mail (DNS). false for computers without DNS access.
    check_email_dns: bool = True

    # Models. "auto" picks cuda when available.
    device: str = "auto"
    models_dir: Path = BACKEND_DIR / "models"
    # Unset model settings pick the trained OR model in models/trained/ when it is there, else the public one.
    # Paths are relative to models_dir. EMBED_MODEL=none turns appearance matching off.
    pose_model: str | None = None
    tracker_config: Path = BACKEND_DIR / "config" / "botsort_reid.yaml"
    embed_model: str | None = None
    surface_config: Path | None = None
    enable_hands: bool = True
    hand_model: str = (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/"
        "rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip"
    )
    hand_input_size: tuple[int, int] = (288, 384)
    enable_depth: bool = True
    depth_model: str = "depth-anything/Depth-Anything-V2-Small-hf"

    # Sampling. Every frame is tracked; heavier stages run less often.
    frame_stride: int = 1
    surface_interval_sec: float = 2.0
    depth_interval_frames: int = 5
    embed_interval_frames: int = 10

    # Proximity features (pixels are measured on the original frame).
    near_px: float = 40.0
    contact_px: float = 8.0
    contact_depth_gap: float = 0.08
    contact_max_speed_px_s: float = 400.0

    # Identity merging for "Person N" labels.
    reid_similarity: float = 0.80
    reid_max_gap_sec: float = 30.0
    reid_max_speed_frac: float = 0.6  # fraction of frame diagonal per second

    # Hand-drawn sterile/nonsterile zones for a fixed camera (JSON, see README), used for
    # uploads that do not send their own `zones`. Empty = segment surfaces automatically.
    default_zones_file: Path | None = None

    # Rule-based breach analysis after tracking (findings shown on the website).
    run_breach_analysis: bool = True
    # Tuned breach rules (training/tune_breaches.py). Default: MODELS_DIR/trained/breach_params.json if present.
    breach_params_file: Path | None = None

    # Final review report written by Google Gemini (API server only; rescrub/report.py).
    # Only findings text and reviewer decisions are sent, never video. Empty key = feature off.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"  # or pin a version listed in Google AI Studio
    gemini_timeout_sec: float = 60.0
    reports_per_hour_per_user: int = 20

    worker_poll_sec: float = 2.0
    db_batch_rows: int = 5000

    @property
    def session_cookie_name(self) -> str:
        # __Host- makes browsers refuse the cookie unless it is Secure, Path=/ and host-only.
        return "__Host-rescrub_session" if self.cookie_secure else "rescrub_session"

    @property
    def session_ttl(self):
        from datetime import timedelta

        return timedelta(hours=self.session_hours)

    @property
    def registration_domain_list(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.registration_email_domains.split(",") if d.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("pose_model", "embed_model", "surface_config", mode="before")
    @classmethod
    def _empty_is_unset(cls, v):
        return None if v == "" else v

    def _trained_or(self, trained: str, public: str) -> str:
        return trained if (self.models_dir / trained).exists() else public

    def resolved_pose_model(self) -> str:
        return self.pose_model or self._trained_or("trained/rescrub-or-pose.pt", "yolo26m-pose.pt")

    def resolved_embed_model(self) -> str | None:
        if self.embed_model and self.embed_model.lower() == "none":
            return None
        return self.embed_model or self._trained_or("trained/rescrub-reid-cls.pt", "yolo26n-cls.pt")

    def resolved_surface_config(self) -> Path:
        if self.surface_config:
            return self.surface_config
        if (self.models_dir / "trained" / "rescrub-or-seg.pt").exists():
            return BACKEND_DIR / "config" / "surfaces_mmor.yaml"
        return BACKEND_DIR / "config" / "surfaces.yaml"

    def resolved_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch

            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"


@lru_cache
def get_settings() -> Settings:
    return Settings()
