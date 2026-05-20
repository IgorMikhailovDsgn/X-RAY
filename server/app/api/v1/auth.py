from fastapi import APIRouter, status

from app.api.v1.deps import SessionDep
from app.auth import service as auth_service
from app.schemas.auth import (
    AuthLoginRequest,
    AuthRefreshRequest,
    AuthRegisterRequest,
    AuthTokenPair,
)

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=AuthTokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: AuthRegisterRequest, session: SessionDep) -> AuthTokenPair:
    return await auth_service.register_user(
        session,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )


@router.post("/login", response_model=AuthTokenPair)
async def login(payload: AuthLoginRequest, session: SessionDep) -> AuthTokenPair:
    return await auth_service.authenticate(
        session, email=payload.email, password=payload.password
    )


@router.post("/refresh", response_model=AuthTokenPair)
async def refresh(payload: AuthRefreshRequest, session: SessionDep) -> AuthTokenPair:
    return await auth_service.refresh_access(session, refresh_token=payload.refresh_token)
