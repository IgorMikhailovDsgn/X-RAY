"""Selectel OpenStack (Nova) wrapper — провижн/удаление GPU-инстансов.

Тонкая обёртка над openstacksdk. openstacksdk сам получает и обновляет
Keystone-токен (24ч) по service-user кредам. Импорт openstack — ленивый внутри
функций, чтобы тесты (которые мокают весь модуль) и окружения без настроенного
Selectel не падали на import-time.

Если ключевые креды/параметры не заданы в config → GpuProviderNotConfigured;
orchestrator это ловит и no-op'ит.
"""

from __future__ import annotations

from typing import Any

from app.config import settings


class GpuProviderNotConfigured(RuntimeError):
    """Не хватает SELECTEL_*/GPU_* настроек для провижна."""


def _require_configured() -> None:
    missing = [
        name
        for name, value in {
            "selectel_username": settings.selectel_username,
            "selectel_password": settings.selectel_password,
            "selectel_project_name": settings.selectel_project_name,
            "selectel_user_domain_name": settings.selectel_user_domain_name,
            "selectel_region": settings.selectel_region,
            "gpu_boot_snapshot_id": settings.gpu_boot_snapshot_id,
            "gpu_availability_zone": settings.gpu_availability_zone,
            "gpu_flavor_id": settings.gpu_flavor_id,
            "gpu_network_id": settings.gpu_network_id,
            # gpu_keypair_name НЕ требуем: на Selectel SSH-ключи account-scoped,
            # Nova create_server их не принимает ("Invalid key_name"). Доступ по
            # SSH к инстансу обеспечивает authorized_keys, запечённый в снапшоте.
        }.items()
        if not value
    ]
    if missing:
        raise GpuProviderNotConfigured(
            f"GPU provider not configured, missing: {', '.join(missing)}"
        )


def is_configured() -> bool:
    try:
        _require_configured()
        return True
    except GpuProviderNotConfigured:
        return False


def _connect() -> Any:
    _require_configured()
    import openstack  # ленивый импорт

    # На Selectel user_domain и project_domain = account_id (одно значение).
    return openstack.connect(
        auth_url=settings.selectel_auth_url,
        username=settings.selectel_username,
        password=settings.selectel_password,
        project_name=settings.selectel_project_name,
        user_domain_name=settings.selectel_user_domain_name,
        project_domain_name=settings.selectel_user_domain_name,
        region_name=settings.selectel_region,
    )


def create_gpu_server(name: str) -> str:
    """Создаёт GPU-сервер, бутящийся из снапшота тома. Возвращает server id.
    Не ждёт ACTIVE — поллинг статуса делает orchestrator в reconcile.

    boot-from-volume: block_device_mapping_v2 с source_type=snapshot создаёт
    свежий volume из gpu_boot_snapshot_id. delete_on_termination=True — том
    удаляется вместе с инстансом (не копим осиротевшие диски = не платим за них).
    """
    conn = _connect()
    # key_name намеренно не передаём: SSH-доступ инъектится через authorized_keys
    # в снапшоте, а Selectel-Nova не принимает account-scoped ключи как key_name.
    server = conn.compute.create_server(
        name=name,
        flavor_id=settings.gpu_flavor_id,
        availability_zone=settings.gpu_availability_zone,
        networks=[{"uuid": settings.gpu_network_id}],
        block_device_mapping_v2=[
            {
                "boot_index": 0,
                "uuid": settings.gpu_boot_snapshot_id,
                "source_type": "snapshot",
                "destination_type": "volume",
                "volume_size": settings.gpu_volume_size,
                "delete_on_termination": True,
            }
        ],
    )
    return server.id


def get_server_status(server_id: str) -> str | None:
    """Nova-статус (ACTIVE/BUILD/ERROR/...). None если сервер не найден
    (уже удалён)."""
    conn = _connect()
    server = conn.compute.find_server(server_id)
    if server is None:
        return None
    return server.status


def delete_server(server_id: str) -> None:
    conn = _connect()
    # ignore_missing — идемпотентно: повторный delete уже удалённого не падает.
    conn.compute.delete_server(server_id, ignore_missing=True, force=True)
