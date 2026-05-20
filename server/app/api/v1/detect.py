import uuid

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.v1.deps import CurrentUser

router = APIRouter(tags=["detect"])


class DetectRequest(BaseModel):
    screenshot_id: uuid.UUID


@router.post("")
async def detect(_payload: DetectRequest, _: CurrentUser) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "no_model_deployed",
            "message": "Inference is unavailable: no model is deployed yet.",
        },
    )
