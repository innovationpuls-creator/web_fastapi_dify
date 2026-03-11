from __future__ import annotations

import asyncio
from pathlib import Path


async def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)


async def move_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(source.replace, destination)


async def read_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def delete_paths(paths: list[Path]) -> None:
    async def _delete(path: Path) -> None:
        await asyncio.to_thread(path.unlink, missing_ok=True)

    await asyncio.gather(*[_delete(path) for path in paths], return_exceptions=True)
