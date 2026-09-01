"""Async pathlib-like access to a sprite filesystem."""

from __future__ import annotations

import posixpath
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Union

import httpx

from ._path import _SpritePathBase
from ._utils import sprite_base_url
from .exceptions import (
    FileNotFoundError_,
    FilesystemError,
    IsADirectoryError_,
)
from .filesystem import SpritePath, _handle_filesystem_error
from .types import FileStat

if TYPE_CHECKING:
    from .async_sprite import AsyncSprite


class AsyncSpritePath(_SpritePathBase["AsyncSpritePath", "AsyncSpriteFilesystem"]):
    """A pathlib-like sprite path with awaitable remote I/O methods."""

    def _build_url(self, endpoint: str) -> str:
        sprite = self._fs._sprite
        return f"{sprite_base_url(sprite.client.base_url, sprite.name)}/fs{endpoint}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._fs._sprite.client.token}"}

    def _handle_error(self, response: httpx.Response, operation: str) -> None:
        _handle_filesystem_error(response, operation, self._path)

    async def _request(
        self,
        method: str,
        endpoint: str,
        operation: str,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._fs._sprite.client._client.request(
                method,
                self._build_url(endpoint),
                headers=kwargs.pop("headers", self._headers()),
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise FilesystemError(str(exc), operation, self._path) from exc
        if not response.is_success:
            self._handle_error(response, operation)
        return response

    def _params(self) -> Dict[str, str]:
        return {"path": self._path, "workingDir": self._fs._working_dir}

    async def exists(self) -> bool:
        """Return whether the remote path exists."""
        try:
            await self.stat()
            return True
        except FileNotFoundError_:
            return False

    async def is_file(self) -> bool:
        """Return whether the remote path is a regular file."""
        try:
            return not (await self.stat()).is_dir
        except FileNotFoundError_:
            return False

    async def is_dir(self) -> bool:
        """Return whether the remote path is a directory."""
        try:
            return (await self.stat()).is_dir
        except FileNotFoundError_:
            return False

    async def stat(self) -> FileStat:
        """Return remote file metadata.

        Returns:
            Metadata for the remote path.

        Raises:
            FileNotFoundError_: If the path does not exist.
        """
        response = await self._request("GET", "/list", "stat", params=self._params())
        entries = response.json().get("entries", [])
        if not entries:
            raise FileNotFoundError_("stat", self._path)
        entry = entries[0]
        mod_time = datetime.now()
        if entry.get("modTime"):
            try:
                mod_time = datetime.fromisoformat(
                    entry["modTime"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass
        return FileStat(
            name=entry.get("name", posixpath.basename(self._path)),
            path=entry.get("path", self._path),
            size=entry.get("size", 0),
            mode=entry.get("mode", "0644"),
            mod_time=mod_time,
            is_dir=entry.get("isDir", False),
        )

    async def read_bytes(self) -> bytes:
        """Read and return the remote file as bytes."""
        response = await self._request("GET", "/read", "read", params=self._params())
        content: bytes = response.content
        return content

    async def read_text(self, encoding: str = "utf-8") -> str:
        """Read and decode the remote file.

        Args:
            encoding: Text encoding used to decode the file.

        Returns:
            Decoded file contents.
        """
        return (await self.read_bytes()).decode(encoding)

    async def write_bytes(
        self, data: bytes, mode: int = 0o644, mkdir_parents: bool = True
    ) -> None:
        """Write bytes to the remote file.

        Args:
            data: Bytes to write.
            mode: File permissions used when creating the file.
            mkdir_parents: Create missing parent directories.
        """
        params = {
            **self._params(),
            "mode": f"{mode:04o}",
            "mkdirParents": str(mkdir_parents).lower(),
        }
        headers = {**self._headers(), "Content-Type": "application/octet-stream"}
        await self._request(
            "PUT", "/write", "write", params=params, headers=headers, content=data
        )

    async def write_text(
        self,
        data: str,
        encoding: str = "utf-8",
        mode: int = 0o644,
        mkdir_parents: bool = True,
    ) -> None:
        """Encode and write text to the remote file.

        Args:
            data: Text to write.
            encoding: Text encoding used to encode the data.
            mode: File permissions used when creating the file.
            mkdir_parents: Create missing parent directories.
        """
        await self.write_bytes(data.encode(encoding), mode, mkdir_parents)

    async def iterdir(self) -> AsyncIterator["AsyncSpritePath"]:
        """Yield paths contained in this remote directory."""
        response = await self._request("GET", "/list", "iterdir", params=self._params())
        for entry in response.json().get("entries", []):
            name = entry.get("name", "")
            if name:
                yield self._new(posixpath.join(self._path, name))

    async def listdir(self) -> List[str]:
        """Return names contained in this remote directory."""
        return [path.name async for path in self.iterdir()]

    async def mkdir(
        self, mode: int = 0o755, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """Create a remote directory.

        Args:
            mode: Directory permissions.
            parents: Create missing parent directories.
            exist_ok: Do not fail when the directory already exists.
        """
        if exist_ok:
            try:
                stat = await self.stat()
                if stat.is_dir:
                    return
                raise FilesystemError(
                    "exists but is not a directory", "mkdir", self._path
                )
            except FileNotFoundError_:
                pass
        keep_path = self / ".keep"
        await keep_path.write_bytes(b"", mode=0o644, mkdir_parents=parents)
        try:
            await keep_path.unlink()
        except FileNotFoundError_:
            pass

    async def unlink(self, missing_ok: bool = False) -> None:
        """Remove a remote file.

        Args:
            missing_ok: Do not fail when the path does not exist.
        """
        params = {**self._params(), "recursive": "false"}
        try:
            await self._request("DELETE", "/delete", "unlink", params=params)
        except FileNotFoundError_:
            if not missing_ok:
                raise

    async def rmdir(self) -> None:
        """Remove an empty remote directory."""
        await self._request(
            "DELETE",
            "/delete",
            "rmdir",
            params={**self._params(), "recursive": "false"},
        )

    async def rmtree(self) -> None:
        """Recursively remove a remote directory and its contents."""
        await self._request(
            "DELETE",
            "/delete",
            "rmtree",
            params={**self._params(), "recursive": "true"},
        )

    def _target_path(self, target: Union[str, "AsyncSpritePath", SpritePath]) -> str:
        if hasattr(target, "_path"):
            return target._path
        if target.startswith("/"):
            return target
        return posixpath.join(posixpath.dirname(self._path), target)

    async def rename(
        self, target: Union[str, "AsyncSpritePath", SpritePath]
    ) -> "AsyncSpritePath":
        """Rename this remote path.

        Args:
            target: Destination path.

        Returns:
            A handle for the destination path.
        """
        target_path = self._target_path(target)
        await self._request(
            "POST",
            "/rename",
            "rename",
            json={
                "source": self._path,
                "dest": target_path,
                "workingDir": self._fs._working_dir,
            },
        )
        return self._new(target_path)

    async def replace(
        self, target: Union[str, "AsyncSpritePath", SpritePath]
    ) -> "AsyncSpritePath":
        """Rename this path, replacing the destination when supported."""
        return await self.rename(target)

    async def copy_to(
        self,
        target: Union[str, "AsyncSpritePath", SpritePath],
        recursive: bool = True,
    ) -> "AsyncSpritePath":
        """Copy this remote path.

        Args:
            target: Destination path.
            recursive: Copy directory contents recursively.

        Returns:
            A handle for the destination path.
        """
        target_path = self._target_path(target)
        await self._request(
            "POST",
            "/copy",
            "copy",
            json={
                "source": self._path,
                "dest": target_path,
                "workingDir": self._fs._working_dir,
                "recursive": recursive,
            },
        )
        return self._new(target_path)

    async def chmod(self, mode: int, recursive: bool = False) -> None:
        """Change remote path permissions.

        Args:
            mode: New permissions.
            recursive: Apply permissions recursively.
        """
        await self._request(
            "POST",
            "/chmod",
            "chmod",
            json={
                "path": self._path,
                "workingDir": self._fs._working_dir,
                "mode": f"{mode:04o}",
                "recursive": recursive,
            },
        )

    async def touch(self, mode: int = 0o644, exist_ok: bool = True) -> None:
        """Create a remote file or update its modification time.

        Args:
            mode: Permissions used when creating the file.
            exist_ok: Do not fail when the file already exists.
        """
        if await self.exists():
            if not exist_ok:
                raise FilesystemError("file exists", "touch", self._path, "EEXIST")
            try:
                await self.write_bytes(await self.read_bytes(), mode=mode)
            except IsADirectoryError_:
                pass
        else:
            await self.write_bytes(b"", mode=mode)


class AsyncSpriteFilesystem:
    """Filesystem factory for :class:`AsyncSpritePath` objects."""

    def __init__(self, sprite: "AsyncSprite", working_dir: str = "/"):
        """Initialize an async filesystem.

        Args:
            sprite: Sprite that owns the remote filesystem.
            working_dir: Base directory for relative paths.
        """
        self._sprite = sprite
        self._working_dir = working_dir.rstrip("/") or "/"

    def _new_path(self, path: str) -> AsyncSpritePath:
        return AsyncSpritePath(self, path)

    def __truediv__(
        self, path: Union[str, AsyncSpritePath, SpritePath]
    ) -> AsyncSpritePath:
        """Create a path relative to this filesystem."""
        if hasattr(path, "_path"):
            return self._new_path(path._path)
        return self._new_path(path)

    def __repr__(self) -> str:
        return (
            f"AsyncSpriteFilesystem(sprite={self._sprite.name!r}, "
            f"working_dir={self._working_dir!r})"
        )

    @property
    def root(self) -> AsyncSpritePath:
        """Return the remote root path."""
        return self._new_path("/")

    @property
    def cwd(self) -> AsyncSpritePath:
        """Return the configured working-directory path."""
        return self._new_path(self._working_dir)

    def path(self, *parts: str) -> AsyncSpritePath:
        """Create a path from one or more components."""
        if not parts:
            return self.cwd
        return self._new_path(posixpath.join(*parts))
