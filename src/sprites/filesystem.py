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
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Union
from urllib.parse import quote
import httpx

from .types import DirEntry, FileStat
from .exceptions import (
    FilesystemError,
    FileNotFoundError_,
    IsADirectoryError_,
    NotADirectoryError_,
    PermissionError_,
    DirectoryNotEmptyError,
)

if TYPE_CHECKING:
    from .sprite import Sprite


class SpritePath:
    """
    A pathlib.Path-like interface for sprite filesystem operations.

    Supports path operations using / operator and standard file methods.
    """

    def __init__(
        self,
        filesystem: "SpriteFilesystem",
        path: str
    ):
        """
        Initialize a SpritePath.

        Args:
            filesystem: Parent SpriteFilesystem instance
            path: Path relative to the filesystem's working directory
        """
        self._fs = filesystem
        self._path = self._normalize_path(path)

    def _normalize_path(self, path: str) -> str:
        """Normalize path to absolute POSIX path."""
        if not path:
            path = "."
        # If relative, join with current path
        if not path.startswith("/"):
            if self._fs._working_dir == "/":
                path = "/" + path
            else:
                path = posixpath.join(self._fs._working_dir, path)
        # Normalize .. and . components
        return posixpath.normpath(path)

    def __truediv__(self, other: Union[str, "SpritePath"]) -> "SpritePath":
        """Support path / "subpath" syntax."""
        if isinstance(other, SpritePath):
            other_path = other._path
        else:
            other_path = str(other)

        if other_path.startswith("/"):
            # Absolute path - use as-is
            new_path = other_path
        else:
            # Relative path - join with current
            new_path = posixpath.join(self._path, other_path)

        return SpritePath(self._fs, new_path)

    def __rtruediv__(self, other: str) -> "SpritePath":
        """Support "path" / sprite_path syntax."""
        return SpritePath(self._fs, posixpath.join(other, self._path))

    def __str__(self) -> str:
        return self._path

    def __repr__(self) -> str:
        return f"SpritePath({self._path!r})"

    def __fspath__(self) -> str:
        return self._path

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, SpritePath):
            return self._path == other._path and self._fs is other._fs
        return False

    def __hash__(self) -> int:
        return hash(self._path)

    @property
    def name(self) -> str:
        """The final component of this path."""
        return posixpath.basename(self._path)

    @property
    def stem(self) -> str:
        """The final component of this path, without its suffix."""
        name = self.name
        dot_idx = name.rfind(".")
        if dot_idx > 0:
            return name[:dot_idx]
        return name

    @property
    def suffix(self) -> str:
        """The file extension of this path."""
        name = self.name
        dot_idx = name.rfind(".")
        if dot_idx > 0:
            return name[dot_idx:]
        return ""

    @property
    def suffixes(self) -> List[str]:
        """A list of the path's file extensions."""
        name = self.name
        if name.startswith("."):
            name = name[1:]
        parts = name.split(".")
        if len(parts) <= 1:
            return []
        return ["." + part for part in parts[1:]]

    @property
    def parent(self) -> "SpritePath":
        """The logical parent of this path."""
        parent_path = posixpath.dirname(self._path)
        if not parent_path:
            parent_path = "/"
        return SpritePath(self._fs, parent_path)

    @property
    def parents(self) -> List["SpritePath"]:
        """A sequence of this path's logical parents."""
        parents = []
        current = self.parent
        while current._path != "/" and current._path != self._path:
            parents.append(current)
            current = current.parent
        if current._path == "/":
            parents.append(current)
        return parents

    @property
    def parts(self) -> tuple:
        """An object providing sequence-like access to the path's components."""
        if self._path == "/":
            return ("/",)
        parts = self._path.split("/")
        if parts[0] == "":
            parts[0] = "/"
        return tuple(p for p in parts if p)

    def is_absolute(self) -> bool:
        """Return whether this path is absolute."""
        return self._path.startswith("/")

    def is_relative_to(self, other: Union[str, "SpritePath"]) -> bool:
        """Return whether this path is relative to another path."""
        if isinstance(other, SpritePath):
            other_path = other._path
        else:
            other_path = str(other)
        return self._path.startswith(other_path.rstrip("/") + "/") or self._path == other_path

    def joinpath(self, *others: Union[str, "SpritePath"]) -> "SpritePath":
        """Combine this path with one or more other paths."""
        result = self
        for other in others:
            result = result / other
        return result

    def with_name(self, name: str) -> "SpritePath":
        """Return a new path with the name changed."""
        return self.parent / name

    def with_stem(self, stem: str) -> "SpritePath":
        """Return a new path with the stem changed."""
        return self.parent / (stem + self.suffix)

    def with_suffix(self, suffix: str) -> "SpritePath":
        """Return a new path with the suffix changed."""
        return self.parent / (self.stem + suffix)

    def relative_to(self, other: Union[str, "SpritePath"]) -> "SpritePath":
        """Return a relative path from this path to another."""
        if isinstance(other, SpritePath):
            other_path = other._path
        else:
            other_path = str(other)

        other_path = other_path.rstrip("/")
        if not self._path.startswith(other_path + "/") and self._path != other_path:
            raise ValueError(f"{self._path} is not relative to {other_path}")

        rel = self._path[len(other_path):].lstrip("/")
        if not rel:
            rel = "."
        return SpritePath(self._fs, rel)

    # ========== Filesystem Operations ==========

    def _build_url(self, endpoint: str) -> str:
        """Build full URL for filesystem endpoint."""
        sprite_name = quote(self._fs._sprite.name, safe="")
        return f"{self._fs._sprite.client.base_url}/v1/sprites/{sprite_name}/fs{endpoint}"

    def _headers(self) -> Dict[str, str]:
        """Get default headers with authorization."""
        return {
            "Authorization": f"Bearer {self._fs._sprite.client.token}",
        }

    def _handle_error(self, response: httpx.Response, operation: str) -> None:
        """Handle HTTP error responses."""
        if response.status_code == 404:
            raise FileNotFoundError_(operation, self._path)

        try:
            data = response.json()
            error_msg = data.get("error", response.text)
            error_code = data.get("code", "")

            if error_code == "EISDIR" or "is a directory" in error_msg.lower():
                raise IsADirectoryError_(operation, self._path)
            elif error_code == "ENOTDIR" or "not a directory" in error_msg.lower():
                raise NotADirectoryError_(operation, self._path)
            elif error_code == "EACCES" or "permission denied" in error_msg.lower():
                raise PermissionError_(operation, self._path)
            elif error_code == "ENOTEMPTY" or "not empty" in error_msg.lower():
                raise DirectoryNotEmptyError(operation, self._path)
            else:
                raise FilesystemError(error_msg, operation, self._path, error_code)
        except (ValueError, KeyError):
            raise FilesystemError(response.text, operation, self._path)

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

        return response.content

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
        self,
        data: bytes,
        mode: int = 0o644,
        mkdir_parents: bool = True
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
        mkdir_parents: bool = True
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
        path_in_response = data.get("path", self._path)

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
        self,
        mode: int = 0o755,
        parents: bool = False,
        exist_ok: bool = False
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
                raise FilesystemError("exists but is not a directory", "mkdir", self._path)
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
        self,
        target: Union[str, "SpritePath"],
        recursive: bool = True
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
