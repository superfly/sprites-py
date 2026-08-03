"""Session management operations for Sprites."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Iterator

import httpx

from sprites._signals import signal_headers
from sprites._utils import quote_path_segment, sprite_base_url
from sprites.exceptions import APIError
from sprites.types import Session, StreamMessage

if TYPE_CHECKING:
    from sprites.sprite import Sprite


class KillStream:
    """A stream of session kill progress messages."""

    def __init__(self, messages: list[StreamMessage]):
        """Initialize the kill stream.

        Args:
            messages: Pre-fetched stream messages.
        """
        self._messages = messages
        self._index = 0

    def __iter__(self) -> Iterator[StreamMessage]:
        """Iterate over stream messages."""
        return self

    def __next__(self) -> StreamMessage:
        """Get the next message from the stream."""
        if self._index >= len(self._messages):
            raise StopIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg

    def process_all(self, handler: Callable[[StreamMessage], None]) -> None:
        """Process all messages with a handler function.

        Args:
            handler: A function that takes a StreamMessage.
        """
        for msg in self._messages:
            handler(msg)

    def close(self) -> None:
        """Close the stream."""
        pass

    def __enter__(self) -> KillStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def list_sessions(sprite: Sprite) -> list[Session]:
    """List active sessions for a sprite.

    Args:
        sprite: The sprite to list sessions for.

    Returns:
        List of active sessions.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{sprite_base_url(sprite.client.base_url, sprite.name)}/exec"

    try:
        response = sprite.client.http_client.get(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to list sessions: {e}") from e

    if response.status_code != 200:
        raise APIError(
            f"Failed to list sessions (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )

    data = response.json()
    sessions_data = data.get("sessions", [])

    sessions = []
    for s in sessions_data:
        # Parse created time
        created_str = s.get("created", "")
        created = datetime.now()
        if created_str:
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Parse last activity time
        last_activity = None
        last_activity_str = s.get("last_activity")
        if last_activity_str:
            try:
                last_activity = datetime.fromisoformat(
                    last_activity_str.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        session = Session(
            id=s.get("id", ""),
            command=s.get("command", ""),
            workdir=s.get("workdir", ""),
            created=created,
            bytes_per_second=int(s.get("bytes_per_second", 0)),
            is_active=s.get("is_active", False),
            last_activity=last_activity,
            tty=s.get("tty", False),
        )
        sessions.append(session)

    return sessions


def kill_session(
    sprite: Sprite,
    session_id: str,
    signal: str = "SIGTERM",
    timeout: int = 10,
) -> KillStream:
    """Kill a session.

    Args:
        sprite: The sprite.
        session_id: The ID of the session to kill.
        signal: The signal to send (default: SIGTERM).
        timeout: Timeout in seconds before force kill (default: 10).

    Returns:
        A stream of kill progress messages.

    Raises:
        APIError: If the API call fails.
    """
    url = (
        f"{sprite_base_url(sprite.client.base_url, sprite.name)}"
        f"/exec/{quote_path_segment(session_id)}/kill"
    )

    payload = {
        "signal": signal,
        "timeout": timeout,
    }

    # Use a separate client for streaming with extended timeout
    with httpx.Client(
        timeout=120.0,
        headers={**signal_headers(), "Authorization": f"Bearer {sprite.client.token}"},
    ) as client:
        try:
            response = client.post(url, json=payload)
        except httpx.RequestError as e:
            raise APIError(f"Failed to kill session: {e}") from e

        if response.status_code != 200:
            raise APIError(
                f"Failed to kill session (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )

        # Parse NDJSON response
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

        return KillStream(messages)
