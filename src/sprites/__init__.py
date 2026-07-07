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

from .client import SpritesClient
from .sprite import Sprite
from .filesystem import SpriteFilesystem, SpritePath
from .control import ControlConnection, OpConn
from .exceptions import (
    SpriteError,
    NetworkError,
    AuthenticationError,
    NotFoundError,
    ExecError,
    FilesystemError,
    FileNotFoundError_,
    IsADirectoryError_,
    NotADirectoryError_,
    PermissionError_,
    DirectoryNotEmptyError,
)
from .types import (
    ClientOptions,
    URLSettings,
    SpriteConfig,
    SpawnOptions,
    ExecOptions,
    ExecResult,
    SpriteInfo,
    ListOptions,
    SpriteList,
    Session,
    Checkpoint,
    StreamMessage,
    PortMapping,
    Service,
    ServiceState,
    ServiceWithState,
    ServiceRequest,
    ServiceLogEvent,
    PolicyRule,
    NetworkPolicy,
    FileStat,
    DirEntry,
)

__version__ = "0.2.0"

__all__ = [
    # Main classes
    "SpritesClient",
    "Sprite",
    "SpriteFilesystem",
    "SpritePath",
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
