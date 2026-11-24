"""Typed application settings."""

from __future__ import annotations

import os
from typing import Optional

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "127.0.0.1"
    port: int = 8000
    reader_token: Optional[SecretStr] = None
    admin_token: Optional[SecretStr] = None
    environment: str = "production"
    docs_enabled: bool = False
    auth_failure_threshold: int = 5
    auth_failure_window_seconds: int = 60
    auth_throttle_max_clients: int = 1024
    cpu_sample_seconds: float = 0.1
    gpu_timeout_seconds: float = 3.0

    database_path: str = Field(default="linux-monitor.db")
    privileged_helper_path: str = Field(default="/usr/local/libexec/linux-monitor-privileged")
    sudo_path: str = Field(default="/usr/bin/sudo")

    @model_validator(mode="after")
    def _validate_tokens_on_init(self) -> "Settings":
        self.validate_tokens()
        return self

    @property
    def is_test_environment(self) -> bool:
        env = self.environment.lower()
        if env in {"test", "testing"}:
            return True
        return "PYTEST_CURRENT_TEST" in os.environ

    def validate_tokens(self) -> None:
        if self.is_test_environment:
            return
        reader = self.reader_token.get_secret_value() if self.reader_token else None
        admin = self.admin_token.get_secret_value() if self.admin_token else None
        if not reader or not admin:
            raise ValueError("READER_TOKEN and ADMIN_TOKEN are required")
        if len(reader) < 32 or len(admin) < 32:
            raise ValueError("tokens must be at least 32 characters")
        if reader == admin:
            raise ValueError("reader and admin tokens must be distinct")

    def reader_value(self) -> Optional[str]:
        return self.reader_token.get_secret_value() if self.reader_token else None

    def admin_value(self) -> Optional[str]:
        return self.admin_token.get_secret_value() if self.admin_token else None