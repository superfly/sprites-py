"""Service management operations for Sprites."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Iterator, Optional

import httpx

from sprites.exceptions import APIError
from sprites.types import ServiceLogEvent, ServiceState, ServiceWithState
from sprites._utils import quote_path_segment, sprite_base_url

if TYPE_CHECKING:
    from sprites.sprite import Sprite


class ServiceStream:
    """A stream of service operation messages."""

    def __init__(self, messages: list[ServiceLogEvent]):
        """Initialize the service stream.

        Args:
            messages: Pre-fetched stream messages.
        """
        self._messages = messages
        self._index = 0

    def __iter__(self) -> Iterator[ServiceLogEvent]:
        """Iterate over stream messages."""
        return self

    def __next__(self) -> ServiceLogEvent:
        """Get the next message from the stream."""
        if self._index >= len(self._messages):
            raise StopIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg

    def process_all(self, handler: callable) -> None:
        """Process all messages with a handler function.

        Args:
            handler: A function that takes a ServiceLogEvent.
        """
        for msg in self._messages:
            handler(msg)

    def close(self) -> None:
        """Close the stream."""
        pass

    def __enter__(self) -> ServiceStream:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _parse_service_with_state(data: dict) -> ServiceWithState:
    """Parse a service with state from API response."""
    state = None
    state_data = data.get("state")
    if state_data:
        started_at = None
        started_at_str = state_data.get("started_at")
        if started_at_str:
            try:
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        next_restart_at = None
        next_restart_str = state_data.get("next_restart_at")
        if next_restart_str:
            try:
                next_restart_at = datetime.fromisoformat(next_restart_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        state = ServiceState(
            name=state_data.get("name", ""),
            status=state_data.get("status", "unknown"),
            pid=state_data.get("pid"),
            started_at=started_at,
            next_restart_at=next_restart_at,
            error=state_data.get("error"),
            restart_count=state_data.get("restart_count", 0),
        )

    return ServiceWithState(
        name=data.get("name", ""),
        cmd=data.get("cmd", ""),
        args=data.get("args", []),
        needs=data.get("needs", []),
        http_port=data.get("http_port"),
        state=state,
    )


def _parse_stream_response(response_text: str) -> list[ServiceLogEvent]:
    """Parse NDJSON stream response into ServiceLogEvent objects."""
    messages = []
    for line in response_text.split("\n"):
        if line.strip():
            try:
                data = json.loads(line)
                messages.append(
                    ServiceLogEvent(
                        type=data.get("type", ""),
                        data=data.get("data"),
                        exit_code=data.get("exit_code"),
                        timestamp=data.get("timestamp"),
                        log_files=data.get("log_files"),
                    )
                )
            except json.JSONDecodeError:
                pass
    return messages


def _sprite_services_url(sprite: Sprite) -> str:
    return f"{sprite_base_url(sprite.client.base_url, sprite.name)}/services"


def _service_url(sprite: Sprite, name: str) -> str:
    return f"{_sprite_services_url(sprite)}/{quote_path_segment(name)}"


def list_services(sprite: Sprite) -> list[ServiceWithState]:
    """List all services for a sprite.

    Args:
        sprite: The sprite to list services for.

    Returns:
        List of services with their state.

    Raises:
        APIError: If the API call fails.
    """
    url = _sprite_services_url(sprite)

    try:
        response = sprite.client.http_client.get(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to list services: {e}") from e

    if response.status_code != 200:
        raise APIError(
            f"Failed to list services (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )

    data = response.json()
    if isinstance(data, dict):
        data = data.get("services", [])
    return [_parse_service_with_state(s) for s in data]


def get_service(sprite: Sprite, name: str) -> ServiceWithState:
    """Get a specific service.

    Args:
        sprite: The sprite.
        name: The name of the service.

    Returns:
        The service with its state.

    Raises:
        APIError: If the API call fails.
    """
    url = _service_url(sprite, name)

    try:
        response = sprite.client.http_client.get(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to get service: {e}") from e

    if response.status_code == 404:
        raise APIError(f"Service not found: {name}", status_code=404)

    if response.status_code != 200:
        raise APIError(
            f"Failed to get service (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )

    return _parse_service_with_state(response.json())


def create_service(
    sprite: Sprite,
    name: str,
    cmd: str,
    args: Optional[list[str]] = None,
    needs: Optional[list[str]] = None,
    http_port: Optional[int] = None,
    duration: Optional[float] = None,
) -> ServiceStream:
    """Create or update a service.

    Args:
        sprite: The sprite.
        name: The name of the service.
        cmd: The command to run.
        args: Command arguments.
        needs: Services this service depends on.
        http_port: HTTP port the service listens on.
        duration: Monitoring duration in seconds.

    Returns:
        A stream of service log events.

    Raises:
        APIError: If the API call fails.
    """
    url = _service_url(sprite, name)
    if duration:
        url += f"?duration={duration}s"

    payload = {"cmd": cmd}
    if args:
        payload["args"] = args
    if needs:
        payload["needs"] = needs
    if http_port is not None:
        payload["http_port"] = http_port

    with httpx.Client(
        timeout=120.0,
        headers={"Authorization": f"Bearer {sprite.client.token}"},
    ) as client:
        try:
            response = client.put(url, json=payload)
        except httpx.RequestError as e:
            raise APIError(f"Failed to create service: {e}") from e

        if response.status_code == 409:
            raise APIError(
                f"Service conflict",
                status_code=409,
                response=response.text,
            )

        if response.status_code != 200:
            raise APIError(
                f"Failed to create service (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )

        return ServiceStream(_parse_stream_response(response.text))


def delete_service(sprite: Sprite, name: str) -> None:
    """Delete a service.

    Args:
        sprite: The sprite.
        name: The name of the service.

    Raises:
        APIError: If the API call fails.
    """
    url = _service_url(sprite, name)

    try:
        response = sprite.client.http_client.delete(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to delete service: {e}") from e

    if response.status_code == 404:
        raise APIError(f"Service not found: {name}", status_code=404)

    if response.status_code == 409:
        raise APIError(
            f"Service conflict",
            status_code=409,
            response=response.text,
        )

    if response.status_code not in (200, 204):
        raise APIError(
            f"Failed to delete service (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )


def start_service(
    sprite: Sprite,
    name: str,
    duration: Optional[float] = None,
) -> ServiceStream:
    """Start a service.

    Args:
        sprite: The sprite.
        name: The name of the service.
        duration: Monitoring duration in seconds.

    Returns:
        A stream of service log events.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_service_url(sprite, name)}/start"
    if duration:
        url += f"?duration={duration}s"

    with httpx.Client(
        timeout=120.0,
        headers={"Authorization": f"Bearer {sprite.client.token}"},
    ) as client:
        try:
            response = client.post(url)
        except httpx.RequestError as e:
            raise APIError(f"Failed to start service: {e}") from e

        if response.status_code == 404:
            raise APIError(f"Service not found: {name}", status_code=404)

        if response.status_code != 200:
            raise APIError(
                f"Failed to start service (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )

        return ServiceStream(_parse_stream_response(response.text))


def stop_service(
    sprite: Sprite,
    name: str,
    timeout: Optional[float] = None,
) -> ServiceStream:
    """Stop a service.

    Args:
        sprite: The sprite.
        name: The name of the service.
        timeout: Timeout in seconds before force stop.

    Returns:
        A stream of service log events.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_service_url(sprite, name)}/stop"
    if timeout:
        url += f"?timeout={timeout}s"

    with httpx.Client(
        timeout=120.0,
        headers={"Authorization": f"Bearer {sprite.client.token}"},
    ) as client:
        try:
            response = client.post(url)
        except httpx.RequestError as e:
            raise APIError(f"Failed to stop service: {e}") from e

        if response.status_code == 404:
            raise APIError(f"Service not found: {name}", status_code=404)

        if response.status_code == 409:
            raise APIError(
                f"Service not running",
                status_code=409,
                response=response.text,
            )

        if response.status_code != 200:
            raise APIError(
                f"Failed to stop service (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )

        return ServiceStream(_parse_stream_response(response.text))


def signal_service(sprite: Sprite, name: str, signal: str) -> None:
    """Send a signal to a running service.

    Args:
        sprite: The sprite.
        name: The name of the service.
        signal: The signal to send (e.g., "SIGTERM", "SIGHUP").

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_services_url(sprite)}/signal"

    payload = {
        "name": name,
        "signal": signal,
    }

    try:
        response = sprite.client.http_client.post(url, json=payload)
    except httpx.RequestError as e:
        raise APIError(f"Failed to signal service: {e}") from e

    if response.status_code == 404:
        raise APIError(f"Service not found: {name}", status_code=404)

    if response.status_code == 409:
        raise APIError(
            f"Service not running",
            status_code=409,
            response=response.text,
        )

    if response.status_code == 400:
        raise APIError(
            f"Invalid signal: {signal}",
            status_code=400,
            response=response.text,
        )

    if response.status_code not in (200, 204):
        raise APIError(
            f"Failed to signal service (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )
