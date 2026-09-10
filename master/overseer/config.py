"""Veylor Overseer Master Configuration."""

from functools import lru_cache
import os
from typing import List, Optional, Union
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="OVERSEER_",
    )

    # Core Application
    PROJECT_NAME: str = "Veylor Overseer"
    VERSION: str = "0.1.0"
    ENV: str = Field(default="development", description="development, production, or test")
    BASE_URL: str = Field(default="http://localhost:8080", description="Master public URL")
    
    # Accepts OVERSEER_SECRET_KEY or plain SECRET_KEY from Kamal secrets
    SECRET_KEY: str = Field(
        default="veylor_overseer_dev_secret_key_minimum_32_chars_long_secure",
        validation_alias=AliasChoices("OVERSEER_SECRET_KEY", "SECRET_KEY"),
        description="Master encryption & session secret key",
    )

    # Database
    MONGODB_URL: str = Field(default="mongodb://localhost:27017")
    MONGODB_DATABASE: str = Field(default="veylor_overseer")

    # Veylor SSO OIDC Integration
    SSO_ISSUER: str = Field(default="http://localhost:8000")
    SSO_CLIENT_ID: str = Field(default="overseer")
    SSO_CLIENT_SECRET: Optional[str] = Field(default=None)
    SSO_REDIRECT_URI: str = Field(default="http://localhost:8080/auth/callback")
    SSO_AUTO_LOGIN_DEV: bool = Field(
        default=True,
        description="Allow automatic development login when SSO is unreachable in development mode",
    )

    # Browser Session
    SESSION_COOKIE_NAME: str = Field(default="overseer_session")
    SESSION_TTL_SECONDS: int = Field(default=2592000)  # 30 days
    SESSION_COOKIE_SECURE: bool = Field(default=False)

    # Ingestion & Monitoring Thresholds
    NODE_STALE_THRESHOLD_SECONDS: int = Field(default=600)    # 10 minutes
    NODE_OFFLINE_THRESHOLD_SECONDS: int = Field(default=1200) # 20 minutes
    SERVICE_MONITOR_WORKER_INTERVAL: int = Field(default=15)  # 15 seconds loop

    # Rate Limiting
    ACTIVATION_RATE_LIMIT_PER_MINUTE: int = Field(default=10)

    # CORS
    CORS_ORIGINS: Union[List[str], str] = Field(
        default=["http://localhost:8080", "http://localhost:8000"]
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
