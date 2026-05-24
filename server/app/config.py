from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "dev", "stage", "prod"]


class Settings(BaseSettings):
    """Конфиг приложения. Локально читается из `.env`; в облаке всё прилетает
    через переменные окружения (Pydantic Settings подхватывает их автоматически).

    Семантика `app_env`:
    - `local` — допустимы дефолты для удобства (например, `redis_url`).
    - `dev/stage/prod` — критичные секреты обязаны быть заданы явно через env-vars.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: AppEnv = "local"

    database_url: str
    alembic_database_url: str

    jwt_secret: str
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 2_592_000

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str = "us-east-1"
    s3_bucket_screenshots: str = "screenshots"
    s3_bucket_localize: str = "localize"
    s3_bucket_models: str = "models"

    redis_url: str = "redis://localhost:6379/0"

    app_version: str = Field(default="0.1.0")
    log_level: str = "INFO"

    cors_dev: bool = False

    @model_validator(mode="after")
    def _no_dev_defaults_in_cloud(self) -> "Settings":
        if self.app_env == "local":
            return self
        # В облачных средах не доверяем фолбэкам — критичные параметры должны
        # быть заданы явно. Pydantic уже отрежет поля без дефолта; здесь — те,
        # у которых дефолт сохранён ради local DX.
        if self.redis_url == "redis://localhost:6379/0":
            raise ValueError(
                f"REDIS_URL must be set explicitly when app_env={self.app_env!r}"
            )
        if self.cors_dev:
            raise ValueError(f"CORS_DEV=true is not allowed when app_env={self.app_env!r}")
        return self


settings = Settings()  # type: ignore[call-arg]
