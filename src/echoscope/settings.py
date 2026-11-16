"""Validated deployment settings shared by the entry points and adapters."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_data_path
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Field(
        default_factory=lambda: user_data_path("EchoScopeRadar", appauthor=False)
    )
    database_url: SecretStr | None = None
    bind: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    demo_port: int = Field(default=8766, ge=1, le=65535)
    server_dir: Path | None = None
    origin: str | None = None
    tls_cert: Path | None = None
    tls_key: Path | None = None
    source_config: Path | None = None
    poll_slots: int = Field(default=4, ge=1, le=32)
    stream_slots: int = Field(default=2, ge=1, le=16)
    retries: int = Field(default=3, ge=0, le=10)
    shutdown_timeout_s: float = Field(default=5, ge=1, le=60)
    session_message_limit: int = Field(default=200, ge=20, le=200)
    retention_interval_s: float = Field(default=86400, ge=60, le=86400)
    sqlite_busy_timeout_ms: int = Field(default=1500, ge=100, le=60000)
    database_pool_size: int = Field(default=5, ge=1, le=32)
    database_pool_timeout_s: float = Field(default=10, ge=1, le=120)
    api_max_body_bytes: int = Field(default=5 * 1024 * 1024, ge=65536, le=20 * 1024 * 1024)
    request_max_bytes: int = Field(default=64 * 1024, ge=8192, le=1024 * 1024)
    login_attempts_per_minute: int = Field(default=8, ge=1, le=30)
    password_hash_slots: int = Field(default=4, ge=1, le=8)
    session_ttl_s: int = Field(default=8 * 3600, ge=300, le=86400)
    max_sessions: int = Field(default=512, ge=1, le=2048)
    max_workspaces: int = Field(default=32, ge=1, le=128)
    local_idle_timeout_s: int = Field(default=180, ge=30, le=86400)

    def database_target(self, filename):
        return (
            self.database_url.get_secret_value() if self.database_url else self.data_dir / filename
        )


def load_environment(path: Path | None = None):
    explicit = path or os.environ.get("ECHOSCOPE_ENV_FILE")
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    persistent = (
        Path(
            os.environ.get("ECHOSCOPE_DATA_DIR")
            or user_data_path("EchoScopeRadar", appauthor=False)
        )
        / "instalacion.env"
    )
    target = (
        Path(explicit).expanduser().resolve()
        if explicit
        else base / ".env"
        if (base / ".env").is_file()
        else persistent
    )
    if explicit and not target.is_file():
        raise ValueError("No se encontró el archivo de entorno indicado.")
    if target.is_file():
        if target.stat().st_size > 65536:
            raise ValueError("El archivo de entorno supera 64 KiB.")
        load_dotenv(target, override=False, interpolate=False, encoding="utf-8-sig")
    return runtime_settings()


def runtime_settings():
    values = {
        key: os.environ[f"ECHOSCOPE_{key.upper()}"]
        for key in RuntimeSettings.model_fields
        if f"ECHOSCOPE_{key.upper()}" in os.environ
    }
    try:
        return RuntimeSettings.model_validate(values)
    except ValidationError as exc:
        fields = ", ".join(str(item["loc"][0]) for item in exc.errors(include_input=False))
        raise ValueError(f"Configuración de entorno inválida. Revisá {fields}.") from None
