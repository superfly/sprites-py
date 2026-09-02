"""
Sprites SDK for Python

A Python SDK for interacting with the Sprites API, providing sprite management,
command execution, filesystem access, checkpoints, services, network policy
management, and optional control-mode WebSocket multiplexing.

Usage:
    from sprites import SpritesClient

    client = SpritesClient(token="your-token")
    sprite = client.sprite("my-sprite")

    # Filesystem operations (pathlib.Path-like API)
    fs = sprite.filesystem("/app")
    config = (fs / "config.json").read_text()
    (fs / "output.txt").write_text("Hello, World!")

    # List directory contents
    for entry in (fs / "data").iterdir():
        print(entry.name)
"""

from .async_client import AsyncSpritesClient
from .async_exec import AsyncCmd
from .async_filesystem import AsyncSpriteFilesystem, AsyncSpritePath
from .async_sprite import AsyncSprite
from .client import SpritesClient
from .control import ControlConnection, OpConn
from .exceptions import (
    AuthenticationError,
    DirectoryNotEmptyError,
    ExecError,
    FileNotFoundError_,
    FilesystemError,
    IsADirectoryError_,
    NetworkError,
    NotADirectoryError_,
    NotFoundError,
    PermissionError_,
    SpriteError,
)
from .filesystem import SpriteFilesystem, SpritePath
from .sprite import Sprite
from .types import (
    Checkpoint,
    ClientOptions,
    DirEntry,
    ExecOptions,
    ExecResult,
    FileStat,
    ListOptions,
    NetworkPolicy,
    PolicyRule,
    PortMapping,
    Service,
    ServiceLogEvent,
    ServiceRequest,
    ServiceState,
    ServiceWithState,
    Session,
    SpawnOptions,
    SpriteConfig,
    SpriteInfo,
    SpriteList,
    StreamMessage,
    URLSettings,
)

__version__ = "0.6.0"

__all__ = [
    # Main classes
    "SpritesClient",
    "AsyncSpritesClient",
    "Sprite",
    "AsyncSprite",
    "SpriteFilesystem",
    "AsyncSpriteFilesystem",
    "SpritePath",
    "AsyncSpritePath",
    "AsyncCmd",
    "ControlConnection",
    "OpConn",
    # Exceptions
    "SpriteError",
    "NetworkError",
    "AuthenticationError",
    "NotFoundError",
    "ExecError",
    "FilesystemError",
    "FileNotFoundError_",
    "IsADirectoryError_",
    "NotADirectoryError_",
    "PermissionError_",
    "DirectoryNotEmptyError",
    # Types
    "ClientOptions",
    "URLSettings",
    "SpriteConfig",
    "SpawnOptions",
    "ExecOptions",
    "ExecResult",
    "SpriteInfo",
    "ListOptions",
    "SpriteList",
    "Session",
    "Checkpoint",
    "StreamMessage",
    "PortMapping",
    "Service",
    "ServiceState",
    "ServiceWithState",
    "ServiceRequest",
    "ServiceLogEvent",
    "PolicyRule",
    "NetworkPolicy",
    "FileStat",
    "DirEntry",
    # Version
    "__version__",
]
