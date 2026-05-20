from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_refresh_token, decode_token
from app.auth.password import hash_password, verify_password
from app.config import settings
from app.core.exceptions import AuthError, ConflictError
from app.models.user import User
from app.schemas.auth import AuthTokenPair


def _token_pair(user: User) -> AuthTokenPair:
    return AuthTokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
        expires_in=settings.jwt_access_ttl_seconds,
    )


async def register_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None,
) -> AuthTokenPair:
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("Email already registered") from exc
    await session.commit()
    await session.refresh(user)
    return _token_pair(user)


async def authenticate(
    session: AsyncSession, *, email: str, password: str
) -> AuthTokenPair:
    result = await session.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    return _token_pair(user)


async def refresh_access(session: AsyncSession, *, refresh_token: str) -> AuthTokenPair:
    user_id = decode_token(refresh_token, "refresh")
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive")
    return _token_pair(user)
