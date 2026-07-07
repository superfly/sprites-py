"""Checkpoint operations for Sprites."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Iterator
from urllib.parse import quote

import httpx

from sprites.exceptions import APIError
from sprites.types import Checkpoint, StreamMessage

if TYPE_CHECKING:
    from sprites.sprite import Sprite


def _sprite_base_url(sprite: Sprite) -> str:
    return f"{sprite.client.base_url}/v1/sprites/{quote(sprite.name, safe='')}"


class CheckpointStream:
    """A stream of checkpoint creation messages."""

    def __init__(self, response: httpx.Response):
        """Initialize the checkpoint stream.

        Args:
            response: The HTTP response with streaming body.
        """
        self._response = response
        self._lines = response.iter_lines()
        self._done = False

    def __iter__(self) -> Iterator[StreamMessage]:
        """Iterate over stream messages."""
        return self

    def __next__(self) -> StreamMessage:
        """Get the next message from the stream."""
        if self._done:
            raise StopIteration

        try:
            for line in self._lines:
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    return StreamMessage(
                        type=data.get("type", ""),
                        data=data.get("data"),
                        error=data.get("error"),
                    )
                except json.JSONDecodeError:
                    continue
        except StopIteration:
            pass

        self._done = True
        raise StopIteration

    def close(self) -> None:
        """Close the stream."""
        self._response.close()

    def __enter__(self) -> CheckpointStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class RestoreStream:
    """A stream of checkpoint restore messages."""

    def __init__(self, response: httpx.Response):
        """Initialize the restore stream.

        Args:
            response: The HTTP response with streaming body.
        """
        self._response = response
        self._lines = response.iter_lines()
        self._done = False

    def __iter__(self) -> Iterator[StreamMessage]:
        """Iterate over stream messages."""
        return self

    def __next__(self) -> StreamMessage:
        """Get the next message from the stream."""
        if self._done:
            raise StopIteration

        try:
            for line in self._lines:
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    return StreamMessage(
                        type=data.get("type", ""),
                        data=data.get("data"),
                        error=data.get("error"),
                    )
                except json.JSONDecodeError:
                    continue
        except StopIteration:
            pass

        self._done = True
        raise StopIteration

    def close(self) -> None:
        """Close the stream."""
        self._response.close()

    def __enter__(self) -> RestoreStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def list_checkpoints(sprite: Sprite, history_filter: str = "") -> list[Checkpoint]:
    """List all checkpoints for a sprite.

    Args:
        sprite: The sprite to list checkpoints for.
        history_filter: Optional filter for checkpoint history.

    Returns:
        List of checkpoint objects.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_base_url(sprite)}/checkpoints"
    if history_filter:
        url += f"?history={history_filter}"

    try:
        response = sprite.client.http_client.get(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to list checkpoints: {e}") from e

    if response.status_code != 200:
        raise APIError(
            f"Failed to list checkpoints (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )

    data = response.json()
    checkpoints = []
    for item in data:
        checkpoint = Checkpoint(
            id=item.get("id", ""),
            create_time=datetime.fromisoformat(item.get("create_time", "").replace("Z", "+00:00")),
            comment=item.get("comment"),
            history=item.get("history"),
        )
        checkpoints.append(checkpoint)

    return checkpoints


def get_checkpoint(sprite: Sprite, checkpoint_id: str) -> Checkpoint:
    """Get a specific checkpoint.

    Args:
        sprite: The sprite.
        checkpoint_id: The ID of the checkpoint.

    Returns:
        The checkpoint object.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_base_url(sprite)}/checkpoints/{quote(checkpoint_id, safe='')}"

    try:
        response = sprite.client.http_client.get(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to get checkpoint: {e}") from e

    if response.status_code != 200:
        raise APIError(
            f"Failed to get checkpoint (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )

    data = response.json()
    return Checkpoint(
        id=data.get("id", ""),
        create_time=datetime.fromisoformat(data.get("create_time", "").replace("Z", "+00:00")),
        comment=data.get("comment"),
        history=data.get("history"),
    )


def create_checkpoint(sprite: Sprite, comment: str = "") -> CheckpointStream:
    """Create a new checkpoint.

    Args:
        sprite: The sprite to checkpoint.
        comment: Optional comment for the checkpoint.

    Returns:
        A stream of checkpoint creation messages.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_base_url(sprite)}/checkpoint"

    payload = {}
    if comment:
        payload["comment"] = comment

    # Use a separate client for streaming with no timeout
    with httpx.Client(
        timeout=None,
        headers={"Authorization": f"Bearer {sprite.client.token}"},
    ) as client:
        try:
            response = client.post(url, json=payload, headers={"Content-Type": "application/json"})
        except httpx.RequestError as e:
            raise APIError(f"Failed to create checkpoint: {e}") from e

        if response.status_code != 200:
            raise APIError(
                f"Failed to create checkpoint (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )

        # For non-streaming response, parse as NDJSON
        messages = []
        for line in response.text.split("\n"):
            if line.strip():
                try:
                    data = json.loads(line)
                    messages.append(
                        StreamMessage(
                            type=data.get("type", ""),
                            data=data.get("data"),
                            error=data.get("error"),
                        )
                    )
                except json.JSONDecodeError:
                    pass

        # Return a simple iterator wrapper
        return _MessageIterator(messages)


def restore_checkpoint(sprite: Sprite, checkpoint_id: str) -> RestoreStream:
    """Restore a checkpoint.

    Args:
        sprite: The sprite to restore.
        checkpoint_id: The ID of the checkpoint to restore.

    Returns:
        A stream of restore messages.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_base_url(sprite)}/checkpoints/{quote(checkpoint_id, safe='')}/restore"

    # Use a separate client for streaming with no timeout
    with httpx.Client(
        timeout=None,
        headers={"Authorization": f"Bearer {sprite.client.token}"},
    ) as client:
        try:
            response = client.post(url)
        except httpx.RequestError as e:
            raise APIError(f"Failed to restore checkpoint: {e}") from e

        if response.status_code != 200:
            raise APIError(
                f"Failed to restore checkpoint (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )

        # For non-streaming response, parse as NDJSON
        messages = []
        for line in response.text.split("\n"):
            if line.strip():
                try:
                    data = json.loads(line)
                    messages.append(
                        StreamMessage(
                            type=data.get("type", ""),
                            data=data.get("data"),
                            error=data.get("error"),
                        )
                    )
                except json.JSONDecodeError:
                    pass

        # Return a simple iterator wrapper
        return _MessageIterator(messages)


class _MessageIterator:
    """Simple iterator over pre-fetched messages."""

    def __init__(self, messages: list[StreamMessage]):
        self._messages = messages
        self._index = 0

    def __iter__(self) -> Iterator[StreamMessage]:
        return self

    def __next__(self) -> StreamMessage:
        if self._index >= len(self._messages):
            raise StopIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg

    def close(self) -> None:
        pass

    def __enter__(self) -> _MessageIterator:
        return self

    def __exit__(self, *args: object) -> None:
        pass
