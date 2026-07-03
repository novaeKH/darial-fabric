from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Secure Workspace Fabric"
    APP_VERSION: str = "0.1.0"

    DATABASE_URL: str

    SECRET_KEY: str
    MASTER_KEK: str

    LOCAL_STORAGE_PATH: str = "storage"
    STORAGE_BACKEND: str = "local"

    SYNTHETIC_AGENT_INTERVAL_SECONDS: int = Field(default=30, ge=5)
    SYNTHETIC_AGENT_MAX_FILES: int = Field(default=50, ge=0)

    MINIO_ENDPOINT: str = "http://localhost:9000"
    MINIO_ACCESS_KEY: str = "swf_minio"
    MINIO_SECRET_KEY: str = "swf_minio_password"
    MINIO_BUCKET: str = "swf-artifacts"
    MINIO_SECURE: bool = False

    BACKEND_CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("STORAGE_BACKEND")
    @classmethod
    def validate_storage_backend(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"local", "minio"}:
            raise ValueError("STORAGE_BACKEND must be either 'local' or 'minio'")
        return normalized

    @field_validator("LOCAL_STORAGE_PATH")
    @classmethod
    def normalize_local_storage_path(cls, value: str) -> str:
        return str(Path(value).as_posix())

    @field_validator("MINIO_ENDPOINT")
    @classmethod
    def normalize_minio_endpoint(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()