from fastapi import APIRouter
from sqlalchemy import select

from app.api.v1.deps import CurrentUser, SessionDep
from app.models.mlops import Deployment, Model
from app.schemas.deployment import DeployedModel, DeployedModelList

router = APIRouter(tags=["models"])


@router.get("/deployed", response_model=DeployedModelList)
async def list_deployed(
    session: SessionDep,
    _: CurrentUser,
) -> DeployedModelList:
    stmt = (
        select(Model.id, Model.model_type, Model.version, Deployment.deployed_at)
        .join(Deployment, Deployment.model_id == Model.id)
        .where(Deployment.is_active.is_(True))
        .order_by(Deployment.deployed_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return DeployedModelList(
        models=[
            DeployedModel(
                id=row.id,
                model_type=row.model_type,
                version=row.version,
                deployed_at=row.deployed_at,
            )
            for row in rows
        ]
    )
