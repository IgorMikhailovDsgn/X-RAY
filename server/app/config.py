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
    # Префиксы в ключах объектов — полезно, когда у тебя один бакет на всё и
    # хочется логически разделить файлы по «папкам». Пустая строка = без префикса
    # (так работает MinIO local + bucket-per-resource cloud-сетап).
    s3_prefix_screenshots: str = ""
    s3_prefix_localize: str = ""
    s3_prefix_models: str = ""

    redis_url: str = "redis://localhost:6379/0"

    # Shared secret для internal API (cron-таски воркера дёргают endpoint'ы на
    # server'е). Без этого токена /api/v1/internal/* отвечает 401, даже с
    # валидным JWT. None = endpoint'ы недоступны (default локально).
    internal_api_token: str | None = None

    # --- Phase 7b: GPU auto-orchestration (Selectel OpenStack) ---
    # Креды service-user'а + параметры инстанса. Если ключевые (auth/image/
    # flavor/network) не заданы — orchestrator no-op'ит (провижить нечем).
    selectel_auth_url: str = "https://cloud.api.selcloud.ru/identity/v3"
    selectel_username: str | None = None
    selectel_password: str | None = None
    selectel_project_name: str | None = None
    selectel_user_domain_name: str | None = None  # обычно = account_id
    selectel_region: str | None = None  # напр. ru-9
    # Selectel GPU-серверы — boot-from-volume (flavor disk=0), Nova createImage
    # для них запрещён политикой. Поэтому бутимся из СНАПШОТА ТОМА (Cinder) через
    # block_device_mapping_v2: новый сервер = свежий volume из снапшота.
    gpu_boot_snapshot_id: str | None = None  # снапшот boot-тома с готовым worker'ом
    gpu_volume_size: int = 40  # размер boot-volume (GB), ≥ исходного
    gpu_availability_zone: str | None = None  # напр. ru-6a (где GPU-ёмкость)
    gpu_flavor_id: str | None = None  # GPU-flavor id (напр. 3100 = 1x RTX 4090)
    gpu_network_id: str | None = None
    gpu_keypair_name: str | None = None
    # Сколько минут без спроса держать инстанс перед удалением.
    gpu_idle_teardown_minutes: int = 20

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
