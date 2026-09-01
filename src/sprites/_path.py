"""Pure path manipulation shared by sync and async filesystem handles."""

from __future__ import annotations

import posixpath
from typing import Any, Generic, List, Protocol, TypeVar, Union, cast


class _WorkingDirFilesystem(Protocol):
    _working_dir: str


PathT = TypeVar("PathT", bound="_SpritePathBase[Any, Any]")
FilesystemT = TypeVar("FilesystemT", bound=_WorkingDirFilesystem)
PathOperand = Union[str, "_SpritePathBase[Any, Any]"]


class _SpritePathBase(Generic[PathT, FilesystemT]):
    """Path operations that do not perform remote I/O."""

    def __init__(self, filesystem: FilesystemT, path: str):
        self._fs = filesystem
        self._path = self._normalize_path(path)

    def _normalize_path(self, path: str) -> str:
        """Normalize a path against the filesystem working directory."""
        if not path:
            path = "."
        if not path.startswith("/"):
            if self._fs._working_dir == "/":
                path = "/" + path
            else:
                path = posixpath.join(self._fs._working_dir, path)
        return posixpath.normpath(path)

    def _new(self, path: str) -> PathT:
        """Create another path with the same concrete type and filesystem."""
        return cast(PathT, type(self)(self._fs, path))

    def __truediv__(self, other: PathOperand) -> PathT:
        """Join this path with another path component."""
        other_path = other._path if isinstance(other, _SpritePathBase) else str(other)
        if other_path.startswith("/"):
            return self._new(other_path)
        return self._new(posixpath.join(self._path, other_path))

    def __rtruediv__(self, other: str) -> PathT:
        """Join a string path on the left of this path."""
        return self._new(posixpath.join(other, self._path))

    def __str__(self) -> str:
        return self._path

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._path!r})"

    def __fspath__(self) -> str:
        return self._path

    def __eq__(self, other: Any) -> bool:
        return (
            type(self) is type(other)
            and self._path == other._path
            and self._fs is other._fs
        )

    def __hash__(self) -> int:
        return hash(self._path)

    @property
    def name(self) -> str:
        """Return the final path component."""
        return posixpath.basename(self._path)

    @property
    def stem(self) -> str:
        """Return the final component without its last suffix."""
        dot_idx = self.name.rfind(".")
        return self.name[:dot_idx] if dot_idx > 0 else self.name

    @property
    def suffix(self) -> str:
        """Return the final component's last suffix."""
        dot_idx = self.name.rfind(".")
        return self.name[dot_idx:] if dot_idx > 0 else ""

    @property
    def suffixes(self) -> List[str]:
        """Return all suffixes on the final path component."""
        name = self.name[1:] if self.name.startswith(".") else self.name
        parts = name.split(".")
        return ["." + part for part in parts[1:]]

    @property
    def parent(self) -> PathT:
        """Return the logical parent path."""
        return self._new(posixpath.dirname(self._path) or "/")

    @property
    def parents(self) -> List[PathT]:
        """Return all logical parents through the root."""
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
        """Return the individual path components."""
        if self._path == "/":
            return ("/",)
        parts = self._path.split("/")
        if parts[0] == "":
            parts[0] = "/"
        return tuple(part for part in parts if part)

    def is_absolute(self) -> bool:
        """Return whether this path is absolute."""
        return self._path.startswith("/")

    def is_relative_to(self, other: PathOperand) -> bool:
        """Return whether this path is within another path."""
        other_path = other._path if isinstance(other, _SpritePathBase) else str(other)
        return (
            self._path.startswith(other_path.rstrip("/") + "/")
            or self._path == other_path
        )

    def joinpath(self, *others: PathOperand) -> PathT:
        """Combine this path with one or more path components."""
        result = cast(PathT, self)
        for other in others:
            result = result / other
        return result

    def with_name(self, name: str) -> PathT:
        """Return a path with the final component replaced."""
        return self._new(posixpath.join(posixpath.dirname(self._path), name))

    def with_stem(self, stem: str) -> PathT:
        """Return a path with the final component's stem replaced."""
        return self.with_name(stem + self.suffix)

    def with_suffix(self, suffix: str) -> PathT:
        """Return a path with the final component's suffix replaced."""
        return self.with_name(self.stem + suffix)

    def relative_to(self, other: PathOperand) -> PathT:
        """Return this path relative to another path.

        Raises:
            ValueError: If this path is not within ``other``.
        """
        other_path = other._path if isinstance(other, _SpritePathBase) else str(other)
        other_path = other_path.rstrip("/")
        if not self._path.startswith(other_path + "/") and self._path != other_path:
            raise ValueError(f"{self._path} is not relative to {other_path}")
        relative = self._path[len(other_path) :].lstrip("/") or "."
        return self._new(relative)
