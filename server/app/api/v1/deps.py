from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_token
from app.config import settings
from app.core.exceptions import AuthError, ForbiddenError
from app.db import SessionLocal
from app.models.user import User
from app.storage import S3Client, get_s3_client


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing or malformed Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_token(token, "access")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    """Гейтит endpoint'ы для админов. Роль читается из БД через get_current_user
    (JWT-payload роль не везёт, чтобы не приходилось перевыпускать токены при
    смене роли)."""
    if user.role != "admin":
        raise ForbiddenError("Admin role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_storage() -> S3Client:
    return get_s3_client()


StorageDep = Annotated[S3Client, Depends(get_storage)]


async def require_internal_token(
    x_internal_token: Annotated[
        str | None, Header(alias="X-Internal-Token")
    ] = None,
) -> None:
    """Гейтит /api/v1/internal/* — endpoint'ы, которые дёргают cron-таски
    воркера. JWT не требуется (worker не пользователь), только shared secret
    в заголовке. Если на сервере токен не настроен — 401 для всех (fail-safe).
    """
    if not settings.internal_api_token:
        raise AuthError("Internal API not configured")
    if x_internal_token != settings.internal_api_token:
        raise AuthError("Invalid internal token")


InternalAuth = Annotated[None, Depends(require_internal_token)]
