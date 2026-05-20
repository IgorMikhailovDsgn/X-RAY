import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt

from app.config import settings
from app.core.exceptions import AuthError

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]


def _encode(subject: str, token_type: TokenType, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(str(user_id), "access", settings.jwt_access_ttl_seconds)


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(str(user_id), "refresh", settings.jwt_refresh_ttl_seconds)


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise AuthError("Invalid token") from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise AuthError(f"Expected {expected_type} token, got {token_type!r}")

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise AuthError("Token missing subject")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise AuthError("Invalid token subject") from exc
