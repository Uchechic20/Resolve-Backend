import os
from unittest.mock import patch
import pytest
from pydantic import ValidationError
from app.core.config import Settings

# Base configuration required for all successful tests
GOOD = dict(
    database_url="postgresql+asyncpg://u:p@localhost:5432/db",
    secret_key="x" * 40,
    rate_limit_enabled=True,
    email_backend="smtp",
    smtp_host="smtp.example.com",
    db_echo=False,
    cors_origins=["https://example.com"],
)

def make(**over):
    return Settings(_env_file=None, **{**GOOD, **over})


def test_valid_development_config():
    s = make(environment="development")
    assert s.environment == "development"
    assert not s.is_production
    assert s.max_upload_bytes == s.max_upload_mb * 1024 * 1024


def test_database_url_must_use_asyncpg():
    with pytest.raises(ValidationError, match="asyncpg"):
        make(database_url="postgresql://u:p@localhost/db")


def test_log_level_is_validated_and_nomalised():
    with patch.dict(os.environ, {}, clear=True):
        # 1. Test default
        s = Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@localhost:5432/db",
            secret_key="x" * 40,
            rate_limit_enabled=False,
            email_backend="smtp",
            smtp_host="smtp.example.com",
            db_echo=False,
            cors_origins=["https://example.com"],
            environment="testing"  # <--- THIS WAS MISSING
        )
        assert s.log_level == "INFO"

        # 2. Test debug
        s_debug = Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@localhost:5432/db",
            secret_key="x" * 40,
            rate_limit_enabled=False,
            email_backend="smtp",
            smtp_host="smtp.example.com",
            db_echo=False,
            cors_origins=["https://example.com"],
            environment="testing", # <--- THIS WAS MISSING
            log_level="debug"
        )
        assert s_debug.log_level == "DEBUG"

        # 3. Test invalid
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                database_url="postgresql+asyncpg://u:p@localhost:5432/db",
                secret_key="x" * 40,
                rate_limit_enabled=False,
                email_backend="smtp",
                smtp_host="smtp.example.com",
                db_echo=False,
                cors_origins=["https://example.com"],
                environment="testing", # <--- THIS WAS MISSING
                log_level="loud"
            )


def test_smtp_backend_needs_a_host():
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        make(email_backend="smtp", smtp_host=None)

    s = make(email_backend="smtp", smtp_host="smtp.example.com")
    assert s.email_backend == "smtp"


# --- Production Validation Tests ---

PROD = dict(environment="production", email_backend="smtp", smtp_host="smtp.example.com")

def test_production_accepts_a_safe_config():
    assert make(**PROD).is_production


@pytest.mark.parametrize(
    "over,message",
    [
        ({"secret_key": "short"}, "32"),
        ({"cors_origins": ["*"]}, "CORS"),
        ({"db_echo": True}, "DB_ECHO"),
        ({"email_backend": "console", "smtp_host": None}, "EMAIL_BACKEND"),
        ({"rate_limit_enabled": False}, "RATE_LIMIT"),
    ],
)
def test_production_rejects_unsafe_settings(over, message):
    with pytest.raises(ValidationError, match=message):
        make(**{**PROD, **over})