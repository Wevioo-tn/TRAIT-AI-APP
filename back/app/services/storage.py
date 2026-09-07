"""File storage abstraction for uploaded scans.

``LocalFileStorage`` is the only implementation today (files on a Docker
volume). It's kept behind this small interface — not because a swap is
planned right now, but because the one thing we already know about this
project is that OCR/NLP will eventually run in a separate worker (Sprint 4)
that also needs to read these files; if that ever means object storage
instead of a shared volume, this is the one place that changes.

Disk I/O is genuinely blocking, so every public method runs it in a thread
via Starlette's ``run_in_threadpool`` rather than stalling the async event
loop.
"""
import uuid
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings


class LocalFileStorage:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or get_settings().upload_dir)

    def _path_for(self, traite_id: uuid.UUID, face: str, filename: str) -> Path:
        # basename() defends against path traversal via a crafted filename.
        safe_name = Path(filename).name
        return self.base_dir / str(traite_id) / f"{face}__{safe_name}"

    def _save_sync(self, traite_id: uuid.UUID, face: str, filename: str, content: bytes) -> str:
        path = self._path_for(traite_id, face, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def _delete_sync(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()

    async def save(self, traite_id: uuid.UUID, face: str, filename: str, content: bytes) -> str:
        return await run_in_threadpool(self._save_sync, traite_id, face, filename, content)

    async def read(self, path: str) -> bytes:
        return await run_in_threadpool(Path(path).read_bytes)

    async def delete(self, path: str) -> None:
        await run_in_threadpool(self._delete_sync, path)


def get_storage() -> LocalFileStorage:
    """FastAPI dependency provider — overridden in tests to point at a
    throwaway directory instead of the real uploads volume."""
    return LocalFileStorage()
