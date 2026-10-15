"""Process configuration loaded from environment variables.

Every secret can be supplied either directly (``FOO``) or as a path to a file
containing it (``FOO_FILE``), which is how Docker secrets are mounted. The
``_FILE`` form always wins and is what the production compose file uses.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


def read_secret(name: str, default: str | None = None) -> str | None:
    path = os.environ.get(f"{name}_FILE")
    if path:
        return Path(path).read_text().strip()
    return os.environ.get(name, default)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # Which component this process runs as; used for logging and Redis names.
    component: str = "app"
    log_level: str = "INFO"

    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "captions"
    db_user: str = "captions_admin"

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_user: str = "default"

    # Public URL the QR codes point at, e.g. https://captions.example.com
    public_base_url: str = "http://localhost:8080"
    # Origin of the admin dashboard; used for CSRF origin checks.
    admin_origin: str = "http://localhost:8081"
    # Set to false only for local plain-HTTP development.
    cookie_secure: bool = True
    admin_require_mfa: bool = True
    admin_session_idle_minutes: int = 480
    admin_session_max_hours: int = 24

    # Number of trusted reverse-proxy hops that append to X-Forwarded-For.
    # Pangolin (Traefik) -> Newt -> app is 1. Add 1 if Cloudflare proxying is on.
    trusted_proxy_hops: int = 1

    # Public caption limits
    public_max_streams: int = 3000
    public_max_streams_per_ip: int = 400  # church Wi-Fi NATs many phones behind one IP
    # Hundreds of phones can share one church Wi-Fi NAT IP and poll status every few seconds.
    public_requests_per_minute_per_ip: int = 12000

    # Ingest limits
    ingest_max_frame_bytes: int = 32000
    ingest_idle_timeout_seconds: float = 15.0
    ingest_allowed_sample_rates: str = "8000,16000,22050,24000,32000,44100,48000"

    static_dir: str = ""
    branding_dir: str = "/app/branding"

    @property
    def database_url(self) -> str:
        password = read_secret("DB_PASSWORD", "") or ""
        return (
            f"postgresql+asyncpg://{quote(self.db_user)}:{quote(password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_password(self) -> str | None:
        return read_secret("REDIS_PASSWORD")

    @property
    def secret_key(self) -> str:
        key = read_secret("APP_SECRET_KEY")
        if not key:
            raise RuntimeError("APP_SECRET_KEY (or APP_SECRET_KEY_FILE) must be set")
        return key

    @property
    def allowed_sample_rates(self) -> set[int]:
        return {int(x) for x in self.ingest_allowed_sample_rates.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
