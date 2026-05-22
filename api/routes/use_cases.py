from __future__ import annotations

from fastapi import APIRouter

from packs.registry import list_packs

router = APIRouter(prefix="/use-cases", tags=["use-cases"])


@router.get("")
def get_use_cases() -> list[dict]:
    """Discover registered use-case packs and their parameter schemas."""
    result = []
    for pack in list_packs():
        result.append(
            {
                "pack_id": str(pack.pack_id),
                "version": pack.version,
                "requires": sorted(pack.requires),
                "parameters_schema": pack.parameters.model_json_schema(),
            }
        )
    return result
