"""Phase 6 — admin role enforcement + model lifecycle endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models.mlops import Deployment, Model


async def _insert_model(
    sessionmaker,
    *,
    model_type: str = "localize",
    version: str = "v1",
    status: str = "candidate",
    metrics: dict[str, Any] | None = None,
) -> uuid.UUID:
    async with sessionmaker() as session:
        model = Model(
            model_type=model_type,
            version=version,
            trained_at=datetime.now(UTC),
            dataset_id=None,
            artifact_path=f"s3://models/{model_type}/{version}/weights.pt",
            metrics=metrics or {"mAP50": 0.5},
            status=status,
        )
        session.add(model)
        await session.commit()
        await session.refresh(model)
        return model.id


async def _insert_deployment(
    sessionmaker, *, model_id: uuid.UUID, is_active: bool = True
) -> None:
    async with sessionmaker() as session:
        session.add(
            Deployment(
                model_id=model_id, deployed_by="auto", is_active=is_active
            )
        )
        await session.commit()


# ------------------- RBAC -------------------


async def test_admin_models_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/admin/models")
    assert resp.status_code == 401


async def test_admin_models_forbids_non_admin(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/admin/models", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden"


# ------------------- list / get -------------------


async def test_list_models_empty_for_admin(client: AsyncClient, admin_headers):
    resp = await client.get("/api/v1/admin/models", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"models": []}


async def test_list_models_with_filter(
    client: AsyncClient, admin_headers, sessionmaker
):
    await _insert_model(sessionmaker, model_type="localize", status="candidate")
    await _insert_model(sessionmaker, model_type="tumor", status="prod")
    resp = await client.get(
        "/api/v1/admin/models?model_type=localize&status=candidate",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["models"]) == 1
    assert body["models"][0]["model_type"] == "localize"
    assert body["models"][0]["status"] == "candidate"


async def test_get_model_not_found(client: AsyncClient, admin_headers):
    resp = await client.get(
        f"/api/v1/admin/models/{uuid.uuid4()}", headers=admin_headers
    )
    assert resp.status_code == 404


# ------------------- promote -------------------


async def test_promote_candidate_to_prod(
    client: AsyncClient, admin_headers, sessionmaker
):
    model_id = await _insert_model(sessionmaker)
    resp = await client.post(
        f"/api/v1/admin/models/{model_id}/promote", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["promoted"]["status"] == "prod"
    assert body["archived"] is None
    # Active deployment появился.
    async with sessionmaker() as session:
        active = (
            await session.execute(
                select(Deployment).where(
                    Deployment.model_id == model_id, Deployment.is_active.is_(True)
                )
            )
        ).scalars().all()
        assert len(active) == 1


async def test_promote_replaces_previous_prod(
    client: AsyncClient, admin_headers, sessionmaker
):
    old_id = await _insert_model(sessionmaker, status="prod", version="v1")
    await _insert_deployment(sessionmaker, model_id=old_id, is_active=True)
    new_id = await _insert_model(sessionmaker, status="candidate", version="v2")

    resp = await client.post(
        f"/api/v1/admin/models/{new_id}/promote", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["promoted"]["id"] == str(new_id)
    assert body["promoted"]["status"] == "prod"
    assert body["archived"]["id"] == str(old_id)
    assert body["archived"]["status"] == "archived"

    # Старый deployment деактивирован, новый активен.
    async with sessionmaker() as session:
        old_active = (
            await session.execute(
                select(Deployment).where(
                    Deployment.model_id == old_id, Deployment.is_active.is_(True)
                )
            )
        ).scalars().all()
        assert old_active == []
        new_active = (
            await session.execute(
                select(Deployment).where(
                    Deployment.model_id == new_id, Deployment.is_active.is_(True)
                )
            )
        ).scalars().all()
        assert len(new_active) == 1


async def test_promote_archived_rejected(
    client: AsyncClient, admin_headers, sessionmaker
):
    model_id = await _insert_model(sessionmaker, status="archived")
    resp = await client.post(
        f"/api/v1/admin/models/{model_id}/promote", headers=admin_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "conflict"


# ------------------- archive -------------------


async def test_archive_candidate(client: AsyncClient, admin_headers, sessionmaker):
    model_id = await _insert_model(sessionmaker, status="candidate")
    resp = await client.post(
        f"/api/v1/admin/models/{model_id}/archive", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


async def test_archive_prod_rejected(
    client: AsyncClient, admin_headers, sessionmaker
):
    model_id = await _insert_model(sessionmaker, status="prod")
    resp = await client.post(
        f"/api/v1/admin/models/{model_id}/archive", headers=admin_headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "validation_error"


async def test_archive_already_archived_noop(
    client: AsyncClient, admin_headers, sessionmaker
):
    model_id = await _insert_model(sessionmaker, status="archived")
    resp = await client.post(
        f"/api/v1/admin/models/{model_id}/archive", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"
