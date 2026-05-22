from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

_ARTIFACT_ROOTS: list[Path] = [
    Path("examples"),
    Path("artifacts"),
]

_ALLOWED_SUFFIXES: set[str] = {
    ".json", ".md", ".txt", ".csv", ".yaml", ".yml", ".html", ".log"
}


def _collect_artifacts() -> list[dict]:
    items = []
    for root in _ARTIFACT_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            stat = path.stat()
            items.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "kind": path.suffix.lstrip("."),
                    "size_bytes": stat.st_size,
                    "last_updated": stat.st_mtime,
                    "root": str(root),
                }
            )
    return items


@router.get("")
def list_artifacts() -> list[dict]:
    """List all artifacts under examples/ and artifacts/."""
    return _collect_artifacts()


@router.get("/{artifact_path:path}")
def get_artifact(artifact_path: str) -> FileResponse:
    """Stream a single artifact file.

    Only paths rooted in examples/ or artifacts/ are served.
    """
    path = Path(artifact_path)

    # Security: must be under one of the allowed roots
    resolved = path.resolve()
    allowed = False
    for root in _ARTIFACT_ROOTS:
        if root.exists():
            try:
                resolved.relative_to(root.resolve())
                allowed = True
                break
            except ValueError:
                pass
        else:
            # Allow if root matches even if not yet existing
            try:
                Path(artifact_path).relative_to(str(root))
                allowed = True
                break
            except ValueError:
                pass

    if not allowed:
        raise HTTPException(status_code=403, detail="Path not in allowed artifact roots")

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=403, detail="File type not served")

    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path=str(path), media_type=media_type or "application/octet-stream")
