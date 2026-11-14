

"""Resolve: central configuration.


"""
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator, SecretStr, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent.parent/ ".env", env_file_encoding="utf-8", extra="ignore"
    )
    database_url:str
    secret_key:str
    upload_dir:str="uploads"
    security_headers_enabled:bool =True
    hsts_active:bool=False
    hsts_max_age_seconds:bool=False
    storage_backend: Literal["local", "s3"] = "local"
    s3_bucket_name: str | None = None
    s3_region: str | None = None
    s3_prefix: str = "attachments/"
    s3_endpoint_url: str | None = None
    s3_kms_key_id: str | None = None
    s3_presign_seconds: int = 60
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    # ---- app ----
    app_name: str = "Resolve"
    environment: Literal["development", "testing", "production"] = "development"
    log_level: str = "INFO"

    cors_origins: list[str] = []

    # Base URL users reach this API at; used to build links in emails.
    public_base_url: str = "http://localhost:8000"

    # ---- email ----
    email_backend: Literal["console", "smtp"] = "smtp"
    email_from: str = "Resolve <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 2525
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    run_worker_in_api:bool=False
    # ---- rate limiting (slowapi syntax: "<count>/<second|minute|hour|day>") ----
    rate_limit_enabled: bool = True
    # memory:// is per-process. With several workers use redis://host:6379/0
    rate_limit_storage_uri: str = "memory://"
    rate_limit_login: str = "10/minute"
    rate_limit_register: str = "5/hour"
    rate_limit_resend: str = "3/hour"
    rate_limit_ticket_create: str = "10/hour"
    rate_limit_write: str = "30/minute"
    rate_limit_upload: str = "20/hour"

    # ---- attachments ----
    max_upload_mb: int = 5
    max_attachments_per_ticket: int = 5


    # ---- database ----
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False  # log every SQL statement (debugging only)

    # ---- auth ----
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    verify_token_hours: int = 24
    bcrypt_rounds: int = 12
    @field_validator("storage_backend",mode="before")
    @classmethod
    def validate_storage_backend(cls,v):
        if isinstance(v,str):
            return v.strip().lower()
        return v
    @field_validator("s3_prefix")
    @classmethod
    def _norm_prefix(cls, v: str) -> str:
        v = v.strip("/")
        return f"{v}/" if v else ""

    @model_validator(mode="after")
    def validate_s3_config(self):
        if self.s3_region is None:
            self.s3_region="eu-north-1"
        if self.storage_backend=="s3":
            if not self.s3_bucket_name:
                raise ValueError("storage_backend=s3 requires a non-empty s3_bucket_name")
        return self


    def _require_s3(self):
        if self.storage_backend == "s3" and not (self.s3_bucket_name and self.s3_region):
            raise ValueError("storage_backend='s3' requires s3_bucket and s3_region")
        return self

    @field_validator("database_url")
    @classmethod
    def must_be_asyncpg(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must start with 'postgresql+asyncpg://' "
                "(the app uses async SQLAlchemy)"
            )
        return v
    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        return v

    @model_validator(mode="after")
    def production_safety(self):
        if self is not None:
            if self.environment == "production":
                if len(self.secret_key) < 32:
                    raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must not contain '*' in production")
            if self.db_echo:
                raise ValueError("DB_ECHO must be off in production")
            if self is not None:
                if self.email_backend == "console":
                    raise ValueError("EMAIL_BACKEND must be 'smtp' in production")
                if not self.rate_limit_enabled:
                    raise ValueError("RATE_LIMIT_ENABLED must be on in production")
                if self.email_backend == "smtp" and not self.smtp_host:
                    raise ValueError("SMTP_HOST is required when EMAIL_BACKEND=smtp")
        return self






    # ---- derived ----
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def sync_database_url(self) -> str:

        return self.database_url.replace("+asyncpg", "+psycopg", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings=get_settings()
