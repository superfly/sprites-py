"""Internal structural types shared by sync and async implementations."""

from __future__ import annotations

from typing import Protocol


class ClientLike(Protocol):
    """Client attributes used by sprite transports."""

    token: str
    base_url: str
    control_mode: bool


class SpriteLike(Protocol):
    """Sprite attributes used by command and control transports."""

    name: str
    _control_mode_supported: bool

    @property
    def client(self) -> ClientLike:
        """Return the client that owns this sprite handle."""
        ...

    def use_control_mode(self) -> bool:
        """Return whether multiplexed control transport should be used."""
        ...
