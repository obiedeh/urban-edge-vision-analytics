from __future__ import annotations

from .base import Pack, PackId
from .moving_object import MovingObjectPack
from .speed_violation import SpeedViolationPack
from .stop_sign import StopSignPack

_REGISTRY: dict[PackId, Pack] = {
    PackId.moving_object: MovingObjectPack(),  # type: ignore[dict-item]
    PackId.speed_violation: SpeedViolationPack(),  # type: ignore[dict-item]
    PackId.stop_sign: StopSignPack(),  # type: ignore[dict-item]
}


def get_pack(pack_id: PackId) -> Pack:
    return _REGISTRY[pack_id]


def list_packs() -> list[Pack]:
    return list(_REGISTRY.values())
