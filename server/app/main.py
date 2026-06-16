from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    admin,
    auth,
    detect,
    detect_annotations,
    health,
    internal,
    localize_annotations,
    localize_images,
    models,
    screenshots,
    tumor_annotations,
)
from app.config import settings
from app.core.exceptions import register_exception_handlers

app = FastAPI(
    title="BrainScan API",
    version=settings.app_version,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)

register_exception_handlers(app)

if settings.cors_dev:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=f"{API_PREFIX}/auth")
app.include_router(health.router, prefix=f"{API_PREFIX}/health")
app.include_router(models.router, prefix=f"{API_PREFIX}/models")
app.include_router(screenshots.router, prefix=f"{API_PREFIX}/screenshots")
app.include_router(localize_images.router, prefix=f"{API_PREFIX}/localize-images")
app.include_router(
    localize_annotations.router, prefix=f"{API_PREFIX}/localize-annotations"
)
app.include_router(tumor_annotations.router, prefix=f"{API_PREFIX}/tumor-annotations")
app.include_router(detect.router, prefix=f"{API_PREFIX}/detect")
app.include_router(
    detect_annotations.router, prefix=f"{API_PREFIX}/detect/annotations"
)
app.include_router(admin.router, prefix=f"{API_PREFIX}/admin")
app.include_router(internal.router, prefix=f"{API_PREFIX}/internal", tags=["internal"])
