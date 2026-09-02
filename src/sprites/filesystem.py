"""
Filesystem support for Sprites SDK with pathlib.Path-like API.

Usage:
    fs = sprite.filesystem("/app")
    path = fs / "config.json"
    content = path.read_text()
    path.write_text("data")
    for entry in (fs / "app").iterdir():
        print(entry.name)
    (fs / "deep/path").mkdir(parents=True)
    (fs / "file.txt").unlink()
    stat = (fs / "file.txt").stat()
    (fs / "old.txt").rename(fs / "new.txt")
    (fs / "src.txt").copy_to(fs / "dst.txt")
    (fs / "script.sh").chmod(0o755)
"""

from __future__ import annotations

import posixpath
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Iterator, List, Union

import httpx

from ._path import _SpritePathBase
from ._utils import sprite_base_url
from .exceptions import (
    DirectoryNotEmptyError,
    FileNotFoundError_,
    FilesystemError,
    IsADirectoryError_,
    NotADirectoryError_,
    PermissionError_,
)
from .types import FileStat

if TYPE_CHECKING:
    from .sprite import Sprite


def _handle_filesystem_error(
    response: httpx.Response, operation: str, path: str
) -> None:
    """Raise the filesystem exception represented by an HTTP response."""
    if response.status_code == 404:
        raise FileNotFoundError_(operation, path)

    try:
        data = response.json()
        error_msg = data.get("error", response.text)
        error_code = data.get("code", "")

        if error_code == "EISDIR" or "is a directory" in error_msg.lower():
            raise IsADirectoryError_(operation, path)
        if error_code == "ENOTDIR" or "not a directory" in error_msg.lower():
            raise NotADirectoryError_(operation, path)
        if error_code == "EACCES" or "permission denied" in error_msg.lower():
            raise PermissionError_(operation, path)
        if error_code == "ENOTEMPTY" or "not empty" in error_msg.lower():
            raise DirectoryNotEmptyError(operation, path)
        raise FilesystemError(error_msg, operation, path, error_code)
    except (ValueError, KeyError):
        raise FilesystemError(response.text, operation, path) from None


class SpritePath(_SpritePathBase["SpritePath", "SpriteFilesystem"]):
    """
    A pathlib.Path-like interface for sprite filesystem operations.

    Supports path operations using / operator and standard file methods.
    """

    # ========== Filesystem Operations ==========

    def _build_url(self, endpoint: str) -> str:
        """Build full URL for filesystem endpoint."""
        return (
            f"{sprite_base_url(self._fs._sprite.client.base_url, self._fs._sprite.name)}"
            f"/fs{endpoint}"
        )

    def _headers(self) -> Dict[str, str]:
        """Get default headers with authorization."""
        return {
            "Authorization": f"Bearer {self._fs._sprite.client.token}",
        }

    def _handle_error(self, response: httpx.Response, operation: str) -> None:
        """Handle HTTP error responses."""
        _handle_filesystem_error(response, operation, self._path)

    def exists(self) -> bool:
        """Return True if this path exists."""
        try:
            self.stat()
            return True
        except FileNotFoundError_:
            return False

    def is_file(self) -> bool:
        """Return True if this path is a regular file."""
        try:
            return not self.stat().is_dir
        except FileNotFoundError_:
            return False

    def is_dir(self) -> bool:
        """Return True if this path is a directory."""
        try:
            return self.stat().is_dir
        except FileNotFoundError_:
            return False

    def stat(self) -> FileStat:
        """
        Return stat information for this path.

        Returns:
            FileStat with name, path, size, mode, mod_time, is_dir
        """
        url = self._build_url("/list")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
        }

        try:
            response = self._fs._sprite.client._client.get(
                url,
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "stat", self._path)

        if not response.is_success:
            self._handle_error(response, "stat")

        data = response.json()
        entries = data.get("entries", [])

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

    def read_bytes(self) -> bytes:
        """
        Read the file contents as bytes.

        Returns:
            File contents as bytes
        """
        url = self._build_url("/read")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
        }

        try:
            response = self._fs._sprite.client._client.get(
                url,
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "read", self._path)

        if not response.is_success:
            self._handle_error(response, "read")

        content: bytes = response.content
        return content

    def read_text(self, encoding: str = "utf-8") -> str:
        """
        Read the file contents as a string.

        Args:
            encoding: Text encoding (default: utf-8)

        Returns:
            File contents as string
        """
        return self.read_bytes().decode(encoding)

    def write_bytes(
        self, data: bytes, mode: int = 0o644, mkdir_parents: bool = True
    ) -> None:
        """
        Write bytes to the file.

        Args:
            data: Data to write
            mode: File permissions (default: 0o644)
            mkdir_parents: Create parent directories if needed (default: True)
        """
        url = self._build_url("/write")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
            "mode": f"{mode:04o}",
            "mkdirParents": str(mkdir_parents).lower(),
        }

        headers = self._headers()
        headers["Content-Type"] = "application/octet-stream"

        try:
            response = self._fs._sprite.client._client.put(
                url,
                headers=headers,
                params=params,
                content=data,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "write", self._path)

        if not response.is_success:
            self._handle_error(response, "write")

    def write_text(
        self,
        data: str,
        encoding: str = "utf-8",
        mode: int = 0o644,
        mkdir_parents: bool = True,
    ) -> None:
        """
        Write a string to the file.

        Args:
            data: String to write
            encoding: Text encoding (default: utf-8)
            mode: File permissions (default: 0o644)
            mkdir_parents: Create parent directories if needed (default: True)
        """
        self.write_bytes(data.encode(encoding), mode, mkdir_parents)

    def iterdir(self) -> Iterator["SpritePath"]:
        """
        Iterate over the directory entries.

        Yields:
            SpritePath for each entry in the directory
        """
        url = self._build_url("/list")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
        }

        try:
            response = self._fs._sprite.client._client.get(
                url,
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "iterdir", self._path)

        if not response.is_success:
            self._handle_error(response, "iterdir")

        data = response.json()

        # Check if we're listing a directory (has entries) or a file (single entry)
        entries = data.get("entries", [])

        # If the path matches and there are entries with different paths, it's a directory
        for entry in entries:
            entry_name = entry.get("name", "")
            if entry_name:
                yield SpritePath(self._fs, posixpath.join(self._path, entry_name))

    def listdir(self) -> List[str]:
        """
        List directory entries as names.

        Returns:
            List of entry names
        """
        return [p.name for p in self.iterdir()]

    def mkdir(
        self, mode: int = 0o755, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """
        Create a directory.

        Args:
            mode: Directory permissions (default: 0o755)
            parents: Create parent directories if needed (default: False)
            exist_ok: Don't raise error if directory exists (default: False)
        """
        # Check if already exists
        if exist_ok:
            try:
                stat = self.stat()
                if stat.is_dir:
                    return
                raise FilesystemError(
                    "exists but is not a directory", "mkdir", self._path
                )
            except FileNotFoundError_:
                pass

        # Create directory by writing a .keep file with mkdirParents
        keep_path = self / ".keep"
        keep_path.write_bytes(b"", mode=0o644, mkdir_parents=parents)

        # Delete the .keep file
        try:
            keep_path.unlink()
        except FileNotFoundError_:
            pass

    def unlink(self, missing_ok: bool = False) -> None:
        """
        Remove a file.

        Args:
            missing_ok: Don't raise error if file doesn't exist (default: False)
        """
        url = self._build_url("/delete")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
            "recursive": "false",
        }

        try:
            response = self._fs._sprite.client._client.delete(
                url,
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "unlink", self._path)

        if response.status_code == 404:
            if not missing_ok:
                raise FileNotFoundError_("unlink", self._path)
            return

        if not response.is_success:
            self._handle_error(response, "unlink")

    def rmdir(self) -> None:
        """Remove an empty directory."""
        url = self._build_url("/delete")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
            "recursive": "false",
        }

        try:
            response = self._fs._sprite.client._client.delete(
                url,
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "rmdir", self._path)

        if not response.is_success:
            self._handle_error(response, "rmdir")

    def rmtree(self) -> None:
        """Remove directory and all contents recursively."""
        url = self._build_url("/delete")
        params = {
            "path": self._path,
            "workingDir": self._fs._working_dir,
            "recursive": "true",
        }

        try:
            response = self._fs._sprite.client._client.delete(
                url,
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "rmtree", self._path)

        if not response.is_success:
            self._handle_error(response, "rmtree")

    def rename(self, target: Union[str, "SpritePath"]) -> "SpritePath":
        """
        Rename this file or directory to the given target.

        Args:
            target: New path (string or SpritePath)

        Returns:
            New SpritePath pointing to the renamed file
        """
        if isinstance(target, SpritePath):
            target_path = target._path
        else:
            if not target.startswith("/"):
                target_path = posixpath.join(posixpath.dirname(self._path), target)
            else:
                target_path = target

        url = self._build_url("/rename")
        headers = self._headers()
        headers["Content-Type"] = "application/json"

        try:
            response = self._fs._sprite.client._client.post(
                url,
                headers=headers,
                json={
                    "source": self._path,
                    "dest": target_path,
                    "workingDir": self._fs._working_dir,
                },
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "rename", self._path)

        if not response.is_success:
            self._handle_error(response, "rename")

        return SpritePath(self._fs, target_path)

    def replace(self, target: Union[str, "SpritePath"]) -> "SpritePath":
        """
        Rename this file or directory to the given target, replacing if exists.

        This is an alias for rename() as the server handles replacement.

        Args:
            target: New path (string or SpritePath)

        Returns:
            New SpritePath pointing to the renamed file
        """
        return self.rename(target)

    def copy_to(
        self, target: Union[str, "SpritePath"], recursive: bool = True
    ) -> "SpritePath":
        """
        Copy this file or directory to the target.

        Args:
            target: Destination path (string or SpritePath)
            recursive: Copy directories recursively (default: True)

        Returns:
            SpritePath pointing to the copied file/directory
        """
        if isinstance(target, SpritePath):
            target_path = target._path
        else:
            if not target.startswith("/"):
                target_path = posixpath.join(posixpath.dirname(self._path), target)
            else:
                target_path = target

        url = self._build_url("/copy")
        headers = self._headers()
        headers["Content-Type"] = "application/json"

        try:
            response = self._fs._sprite.client._client.post(
                url,
                headers=headers,
                json={
                    "source": self._path,
                    "dest": target_path,
                    "workingDir": self._fs._working_dir,
                    "recursive": recursive,
                },
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "copy", self._path)

        if not response.is_success:
            self._handle_error(response, "copy")

        return SpritePath(self._fs, target_path)

    def chmod(self, mode: int, recursive: bool = False) -> None:
        """
        Change file/directory permissions.

        Args:
            mode: New permissions (e.g., 0o755)
            recursive: Apply recursively to directory contents (default: False)
        """
        url = self._build_url("/chmod")
        headers = self._headers()
        headers["Content-Type"] = "application/json"

        try:
            response = self._fs._sprite.client._client.post(
                url,
                headers=headers,
                json={
                    "path": self._path,
                    "workingDir": self._fs._working_dir,
                    "mode": f"{mode:04o}",
                    "recursive": recursive,
                },
            )
        except httpx.RequestError as e:
            raise FilesystemError(str(e), "chmod", self._path)

        if not response.is_success:
            self._handle_error(response, "chmod")

    def touch(self, mode: int = 0o644, exist_ok: bool = True) -> None:
        """
        Create a file or update its modification time.

        Args:
            mode: File permissions if created (default: 0o644)
            exist_ok: Don't raise error if file exists (default: True)
        """
        if self.exists():
            if not exist_ok:
                raise FilesystemError("file exists", "touch", self._path, "EEXIST")
            # Just read and write to update mtime
            try:
                content = self.read_bytes()
                self.write_bytes(content, mode=mode)
            except IsADirectoryError_:
                pass  # Can't touch directories this way
        else:
            self.write_bytes(b"", mode=mode)


class SpriteFilesystem:
    """
    A filesystem interface for a sprite that provides pathlib.Path-like access.

    Usage:
        fs = sprite.filesystem("/app")
        path = fs / "config.json"
        content = path.read_text()
    """

    def __init__(self, sprite: "Sprite", working_dir: str = "/"):
        """
        Initialize a SpriteFilesystem.

        Args:
            sprite: Sprite instance
            working_dir: Working directory for all operations (default: "/")
        """
        self._sprite = sprite
        self._working_dir = working_dir.rstrip("/") or "/"

    def __truediv__(self, path: Union[str, SpritePath]) -> SpritePath:
        """Support fs / "path" syntax."""
        if isinstance(path, SpritePath):
            return SpritePath(self, path._path)
        return SpritePath(self, path)

    def __repr__(self) -> str:
        return f"SpriteFilesystem(sprite={self._sprite.name!r}, working_dir={self._working_dir!r})"

    @property
    def root(self) -> SpritePath:
        """Get a SpritePath for the root directory."""
        return SpritePath(self, "/")

    @property
    def cwd(self) -> SpritePath:
        """Get a SpritePath for the current working directory."""
        return SpritePath(self, self._working_dir)

    def path(self, *parts: str) -> SpritePath:
        """
        Create a SpritePath from path parts.

        Args:
            *parts: Path components to join

        Returns:
            SpritePath for the joined path
        """
        if not parts:
            return SpritePath(self, self._working_dir)
        return SpritePath(self, posixpath.join(*parts))
