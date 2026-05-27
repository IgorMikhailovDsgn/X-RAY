"""Pytest fixtures для Phase B.

Тесты предполагают, что docker compose стек поднят и БД `brainscan_test`
существует с применёнными миграциями. См. server/README.md.

S3 мокается in-memory `FakeS3Client` (избегаем зависимости от moto).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Перед импортом приложения подменяем настройки на тестовые.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://brainscan:brainscan_dev@localhost:5432/brainscan_test",
)
os.environ.setdefault(
    "ALEMBIC_DATABASE_URL",
    "postgresql+psycopg2://brainscan:brainscan_dev@localhost:5432/brainscan_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-in-prod")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")

from app.api.v1.deps import get_session, get_storage
from app.config import settings
from app.main import app
from app.storage import S3Client


class FakeS3Client(S3Client):
    """In-memory совместимый со S3Client. Хранит загруженные ключи в словаре."""

    def __init__(self) -> None:
        # Намеренно не вызываем super().__init__ — _client не нужен.
        self.objects: dict[tuple[str, str], bytes] = {}
        self.buckets: set[str] = {
            settings.s3_bucket_screenshots,
            settings.s3_bucket_localize,
            settings.s3_bucket_models,
        }

    async def upload_bytes(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        self.objects[(bucket, key)] = content
        return f"s3://{bucket}/{key}"

    async def head_bucket(self, bucket: str) -> None:
        if bucket not in self.buckets:
            raise RuntimeError(f"bucket {bucket} not found")


@pytest.fixture
def engine():
    # NullPool + function-scope: каждый тест берёт свой event loop у pytest-asyncio,
    # asyncpg-коннект жёстко связан с loop'ом — переиспользование через пул роняет
    # сессию с "another operation is in progress".
    engine = create_async_engine(settings.database_url, future=True, poolclass=NullPool)
    yield engine


@pytest.fixture
def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


_TABLES_TO_TRUNCATE = [
    # Phase 5a additions:
    "training_candidates",
    "dataset_builds",
    # Существовавшие до 5a — порядок (от листьев к корню) важен только без
    # CASCADE, но мы TRUNCATE с CASCADE, поэтому он только для читаемости.
    "tumor_annotations",
    "tumor_detections",
    "localize_images",
    "localize_annotations",
    "localize_detections",
    "screenshots",
    "deployments",
    "models",
    "datasets",
    "users",
]


@pytest.fixture(autouse=True)
async def _truncate(sessionmaker) -> AsyncIterator[None]:
    async with sessionmaker() as session:
        await session.execute(
            text(f"TRUNCATE {', '.join(_TABLES_TO_TRUNCATE)} RESTART IDENTITY CASCADE")
        )
        await session.commit()
    yield


@pytest.fixture
def fake_s3() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
async def client(sessionmaker, fake_s3: FakeS3Client) -> AsyncIterator[AsyncClient]:
    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_storage] = lambda: fake_s3
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _register_and_login(client: AsyncClient, email: str | None = None) -> dict[str, Any]:
    email = email or f"user-{uuid.uuid4()}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": "Test"},
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "tokens": resp.json()}


@pytest.fixture
async def auth(client: AsyncClient) -> dict[str, Any]:
    return await _register_and_login(client)


@pytest.fixture
def auth_headers(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['tokens']['access_token']}"}


@pytest.fixture
async def admin_headers(client: AsyncClient, sessionmaker, auth) -> dict[str, str]:
    """Регистрирует обычного юзера и промоутит до admin прямым UPDATE.
    Register endpoint о ролях не знает (это осознанный design — Phase 6
    рассказывает почему: role даётся через миграцию/руками)."""
    # Импорт локально, чтобы не плодить FK-нагрузку при load-time.
    from sqlalchemy import update

    from app.models.user import User

    async with sessionmaker() as session:
        await session.execute(
            update(User).where(User.email == auth["email"]).values(role="admin")
        )
        await session.commit()
    return {"Authorization": f"Bearer {auth['tokens']['access_token']}"}
