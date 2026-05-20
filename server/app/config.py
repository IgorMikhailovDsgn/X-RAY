from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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


settings = Settings()  # type: ignore[call-arg]
