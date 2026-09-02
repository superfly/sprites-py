"""Asynchronous sprite handle."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import httpx

from ._utils import parse_sprite_info, quote_path_segment, sprite_base_url
from .checkpoint import (
    CHECKPOINT_TIMEOUT,
    CheckpointStream,
    RestoreStream,
    _MessageIterator,
)
from .exceptions import APIError, NetworkError, NotFoundError, SpriteError
from .services import ServiceStream, _parse_service_with_state, _parse_stream_response
from .types import (
    Checkpoint,
    NetworkPolicy,
    PolicyRule,
    ServiceWithState,
    Session,
    SpriteConfig,
    StreamMessage,
    URLSettings,
)

if TYPE_CHECKING:
    from .async_client import AsyncSpritesClient
    from .async_exec import AsyncCmd
    from .async_filesystem import AsyncSpriteFilesystem
    from .control import ControlConnection
    from .exec import CompletedProcess


class AsyncSprite:
    """A sprite whose I/O methods are native coroutines."""

    def __init__(self, name: str, client: "AsyncSpritesClient"):
        """Initialize an async sprite handle.

        Args:
            name: Sprite name.
            client: Async client that owns the handle.
        """
        self.name = name
        self.client = client
        self._control_mode_supported = True
        self.id: Optional[str] = None
        self.organization_name: Optional[str] = None
        self.status: Optional[str] = None
        self.config: Optional[SpriteConfig] = None
        self.environment: Optional[Dict[str, str]] = None
        self.created_at: Optional[datetime] = None
        self.updated_at: Optional[datetime] = None
        self.bucket_name: Optional[str] = None
        self.primary_region: Optional[str] = None
        self.url: Optional[str] = None
        self.url_settings: Optional[URLSettings] = None
        self.version: Optional[str] = None
        self.environment_version: Optional[str] = None
        self.labels: List[str] = []
        self.last_running_at: Optional[datetime] = None
        self.last_warming_at: Optional[datetime] = None

    def _update_from_info(self, info: Dict[str, Any]) -> None:
        parsed = parse_sprite_info(info)
        self.id = parsed.id
        self.organization_name = parsed.organization
        self.status = parsed.status
        self.config = parsed.config
        self.environment = parsed.environment
        self.created_at = parsed.created_at
        self.updated_at = parsed.updated_at
        self.url = parsed.url
        self.primary_region = parsed.primary_region
        self.bucket_name = parsed.bucket_name
        self.url_settings = parsed.url_settings
        self.version = parsed.version
        self.environment_version = parsed.environment_version
        self.labels = parsed.labels
        self.last_running_at = parsed.last_running_at
        self.last_warming_at = parsed.last_warming_at

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.client.token}",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        return sprite_base_url(self.client.base_url, self.name)

    def filesystem(self, working_dir: str = "/") -> "AsyncSpriteFilesystem":
        """Return an async pathlib-like filesystem interface.

        Args:
            working_dir: Base directory for relative paths.

        Returns:
            An async filesystem bound to this sprite.
        """
        from .async_filesystem import AsyncSpriteFilesystem

        return AsyncSpriteFilesystem(self, working_dir)

    async def destroy(self) -> None:
        """Destroy this sprite."""
        await self.client.destroy_sprite(self.name)

    async def delete(self) -> None:
        """Alias for :meth:`destroy`."""
        await self.destroy()

    async def upgrade(self) -> None:
        """Upgrade this sprite to the latest runtime version."""
        await self.client.upgrade_sprite(self.name)

    async def update_url_settings(self, settings: URLSettings) -> None:
        """Update this sprite's URL access settings.

        Args:
            settings: Replacement URL access settings.
        """
        await self.client.update_url_settings(self.name, settings)

    async def update(
        self,
        *,
        url_settings: Optional[URLSettings] = None,
        labels: Optional[List[str]] = None,
    ) -> "AsyncSprite":
        """Partially update mutable settings.

        Args:
            url_settings: Replacement URL access settings, when supplied.
            labels: Replacement labels, when supplied.

        Returns:
            A populated handle containing the updated metadata.
        """
        return await self.client.update_sprite(
            self.name, url_settings=url_settings, labels=labels
        )

    async def list_sessions(self) -> List[Session]:
        """List active command sessions.

        Returns:
            Active sessions reported by the sprite.
        """
        try:
            response = await self.client._client.get(
                f"{self._base_url()}/exec", headers=self._headers()
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error listing sessions: {exc}") from exc
        if not response.is_success:
            raise SpriteError(
                f"Failed to list sessions (status {response.status_code}): {response.text}"
            )

        sessions = []
        for item in response.json().get("sessions", []):
            created = _parse_time(item.get("created")) or datetime.now()
            sessions.append(
                Session(
                    id=item.get("id", ""),
                    command=item.get("command", ""),
                    workdir=item.get("workdir", ""),
                    created=created,
                    bytes_per_second=int(item.get("bytes_per_second", 0)),
                    is_active=item.get("is_active", False),
                    tty=item.get("tty", False),
                    last_activity=_parse_time(item.get("last_activity")),
                )
            )
        return sessions

    async def list_checkpoints(
        self, history_filter: Optional[str] = None
    ) -> List[Checkpoint]:
        """List checkpoints.

        Args:
            history_filter: Optional checkpoint-history filter.

        Returns:
            Matching checkpoints.
        """
        params = {"history": history_filter} if history_filter else None
        try:
            response = await self.client._client.get(
                f"{self._base_url()}/checkpoints",
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error listing checkpoints: {exc}") from exc
        if not response.is_success:
            raise SpriteError(
                f"Failed to list checkpoints (status {response.status_code}): {response.text}"
            )
        return [_checkpoint_from_dict(item) for item in response.json()]

    async def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Get checkpoint details.

        Args:
            checkpoint_id: Checkpoint identifier.

        Returns:
            The requested checkpoint.

        Raises:
            NotFoundError: If the checkpoint does not exist.
        """
        try:
            response = await self.client._client.get(
                f"{self._base_url()}/checkpoints/{quote_path_segment(checkpoint_id)}",
                headers=self._headers(),
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error getting checkpoint: {exc}") from exc
        if response.status_code == 404:
            raise NotFoundError(f"Checkpoint not found: {checkpoint_id}")
        if not response.is_success:
            raise SpriteError(
                f"Failed to get checkpoint (status {response.status_code}): {response.text}"
            )
        return _checkpoint_from_dict(response.json())

    async def create_checkpoint(
        self,
        comment: str = "",
        *,
        timeout: Union[float, httpx.Timeout] = CHECKPOINT_TIMEOUT,
    ) -> CheckpointStream:
        """Create a checkpoint and return its progress messages.

        Args:
            comment: Optional checkpoint comment.
            timeout: HTTP timeout in seconds or an ``httpx.Timeout``.

        Returns:
            A finite iterator of checkpoint progress messages.
        """
        payload = {"comment": comment} if comment else {}
        try:
            response = await self.client._client.post(
                f"{self._base_url()}/checkpoint",
                headers=self._headers(),
                json=payload,
                timeout=timeout,
            )
        except httpx.RequestError as exc:
            raise APIError(f"Failed to create checkpoint: {exc}") from exc
        if response.status_code != 200:
            raise APIError(
                f"Failed to create checkpoint (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )
        return _MessageIterator(_parse_messages(response.text))

    async def restore_checkpoint(
        self,
        checkpoint_id: str,
        *,
        timeout: Union[float, httpx.Timeout] = CHECKPOINT_TIMEOUT,
    ) -> RestoreStream:
        """Restore a checkpoint and return its progress messages.

        Args:
            checkpoint_id: Checkpoint identifier.
            timeout: HTTP timeout in seconds or an ``httpx.Timeout``.

        Returns:
            A finite iterator of restore progress messages.
        """
        url = (
            f"{self._base_url()}/checkpoints/"
            f"{quote_path_segment(checkpoint_id)}/restore"
        )
        try:
            response = await self.client._client.post(
                url, headers=self._headers(), timeout=timeout
            )
        except httpx.RequestError as exc:
            raise APIError(f"Failed to restore checkpoint: {exc}") from exc
        if response.status_code != 200:
            raise APIError(
                f"Failed to restore checkpoint (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )
        return _MessageIterator(_parse_messages(response.text))

    def command(
        self,
        *args: str,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        tty: bool = False,
        tty_rows: int = 24,
        tty_cols: int = 80,
    ) -> "AsyncCmd":
        """Create an asynchronously executable command.

        Args:
            *args: Command and arguments.
            env: Environment variables.
            cwd: Working directory.
            timeout: Maximum execution time in seconds.
            stdin: Optional binary stdin source.
            stdout: Optional binary stdout sink.
            stderr: Optional binary stderr sink.
            tty: Whether to allocate a pseudo-terminal.
            tty_rows: Terminal height in rows.
            tty_cols: Terminal width in columns.

        Returns:
            A command that can be awaited through ``run`` or ``output``.
        """
        from .async_exec import AsyncCmd

        return AsyncCmd(
            sprite=self,
            args=list(args),
            env=env,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            tty=tty,
            tty_rows=tty_rows,
            tty_cols=tty_cols,
            timeout=timeout,
        )

    async def run(
        self,
        *args: str,
        capture_output: bool = False,
        timeout: Optional[float] = None,
        check: bool = False,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        tty: bool = False,
        tty_rows: int = 24,
        tty_cols: int = 80,
    ) -> "CompletedProcess":
        """Run a command asynchronously, mirroring ``subprocess.run``.

        Args:
            *args: Command and arguments.
            capture_output: Capture stdout and stderr in the result.
            timeout: Maximum execution time in seconds.
            check: Raise ``ExitError`` for a non-zero exit status.
            env: Environment variables.
            cwd: Working directory.
            tty: Whether to allocate a pseudo-terminal.
            tty_rows: Terminal height in rows.
            tty_cols: Terminal width in columns.

        Returns:
            Completed command information.
        """
        from .async_exec import run

        return await run(
            self,
            *args,
            capture_output=capture_output,
            timeout=timeout,
            check=check,
            env=env,
            cwd=cwd,
            tty=tty,
            tty_rows=tty_rows,
            tty_cols=tty_cols,
        )

    def attach_session(
        self, session_id: str, timeout: Optional[float] = None
    ) -> "AsyncCmd":
        """Create a command attached to an existing session.

        Args:
            session_id: Existing session identifier.
            timeout: Maximum attachment time in seconds.

        Returns:
            An asynchronously executable attached command.
        """
        from .async_exec import AsyncCmd

        return AsyncCmd(self, [], session_id=session_id, timeout=timeout)

    async def list_services(self) -> List[ServiceWithState]:
        """List configured services and their current state."""
        response = await self._service_request(
            "GET", f"{self._base_url()}/services", "list services"
        )
        data = response.json()
        if isinstance(data, dict):
            data = data.get("services", [])
        return [_parse_service_with_state(item) for item in data]

    async def get_service(self, service_name: str) -> ServiceWithState:
        """Get a service by name.

        Args:
            service_name: Service name.

        Returns:
            The service and its current state.
        """
        response = await self._service_request(
            "GET",
            f"{self._base_url()}/services/{quote_path_segment(service_name)}",
            "get service",
        )
        return _parse_service_with_state(response.json())

    async def delete_service(self, service_name: str) -> None:
        """Delete a service.

        Args:
            service_name: Service name.
        """
        await self._service_request(
            "DELETE",
            f"{self._base_url()}/services/{quote_path_segment(service_name)}",
            "delete service",
            valid_statuses=(200, 204),
        )

    async def create_service(
        self,
        service_name: str,
        cmd: str,
        args: Optional[List[str]] = None,
        needs: Optional[List[str]] = None,
        http_port: Optional[int] = None,
        duration: Optional[float] = None,
        *,
        env: Optional[Dict[str, str]] = None,
        dir: Optional[str] = None,
    ) -> ServiceStream:
        """Create or update a service.

        Args:
            service_name: Service name.
            cmd: Executable to run.
            args: Command arguments.
            needs: Service dependencies.
            http_port: HTTP port exposed by the service.
            duration: Monitoring duration in seconds.
            env: Environment variables.
            dir: Working directory.

        Returns:
            A finite iterator of service events.
        """
        url = f"{self._base_url()}/services/{quote_path_segment(service_name)}"
        if duration:
            url += f"?duration={duration}s"
        payload: Dict[str, object] = {"cmd": cmd}
        if args:
            payload["args"] = args
        if needs:
            payload["needs"] = needs
        if http_port is not None:
            payload["http_port"] = http_port
        if env is not None:
            payload["env"] = env
        if dir is not None:
            payload["dir"] = dir
        response = await self._service_request(
            "PUT", url, "create service", json=payload, timeout=120.0
        )
        return ServiceStream(_parse_stream_response(response.text))

    async def start_service(
        self, service_name: str, duration: Optional[float] = None
    ) -> ServiceStream:
        """Start a service and return its events.

        Args:
            service_name: Service name.
            duration: Monitoring duration in seconds.

        Returns:
            A finite iterator of service events.
        """
        url = f"{self._base_url()}/services/{quote_path_segment(service_name)}/start"
        if duration:
            url += f"?duration={duration}s"
        response = await self._service_request(
            "POST", url, "start service", timeout=120.0
        )
        return ServiceStream(_parse_stream_response(response.text))

    async def stop_service(
        self, service_name: str, timeout: Optional[float] = None
    ) -> ServiceStream:
        """Stop a service and return its events.

        Args:
            service_name: Service name.
            timeout: Grace period before force stopping.

        Returns:
            A finite iterator of service events.
        """
        url = f"{self._base_url()}/services/{quote_path_segment(service_name)}/stop"
        if timeout:
            url += f"?timeout={timeout}s"
        response = await self._service_request(
            "POST", url, "stop service", timeout=120.0
        )
        return ServiceStream(_parse_stream_response(response.text))

    async def signal_service(self, service_name: str, signal: str) -> None:
        """Send a signal to a running service.

        Args:
            service_name: Service name.
            signal: Signal name, such as ``SIGTERM``.
        """
        await self._service_request(
            "POST",
            f"{self._base_url()}/services/signal",
            "signal service",
            json={"name": service_name, "signal": signal},
            valid_statuses=(200, 204),
        )

    async def _service_request(
        self,
        method: str,
        url: str,
        operation: str,
        valid_statuses: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self.client._client.request(
                method, url, headers=self._headers(), **kwargs
            )
        except httpx.RequestError as exc:
            raise APIError(f"Failed to {operation}: {exc}") from exc
        if response.status_code not in valid_statuses:
            raise APIError(
                f"Failed to {operation} (status {response.status_code})",
                status_code=response.status_code,
                response=response.text,
            )
        return response

    async def get_network_policy(self) -> NetworkPolicy:
        """Get the sprite's current network policy."""
        try:
            response = await self.client._client.get(
                f"{self._base_url()}/policy/network", headers=self._headers()
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error getting network policy: {exc}") from exc
        if not response.is_success:
            raise SpriteError(
                f"Failed to get network policy (status {response.status_code}): {response.text}"
            )
        return NetworkPolicy(
            rules=[
                PolicyRule(
                    domain=item.get("domain"),
                    action=item.get("action"),
                    include=item.get("include"),
                )
                for item in response.json().get("rules", [])
            ]
        )

    async def update_network_policy(self, policy: NetworkPolicy) -> None:
        """Replace the sprite's network policy.

        Args:
            policy: Replacement network policy.
        """
        rules = [
            {
                key: value
                for key, value in {
                    "domain": rule.domain,
                    "action": rule.action,
                    "include": rule.include,
                }.items()
                if value is not None
            }
            for rule in policy.rules
        ]
        try:
            response = await self.client._client.post(
                f"{self._base_url()}/policy/network",
                headers=self._headers(),
                json={"rules": rules},
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error updating network policy: {exc}") from exc
        if not response.is_success:
            raise SpriteError(
                f"Failed to update network policy (status {response.status_code}): {response.text}"
            )

    def use_control_mode(self) -> bool:
        """Return whether multiplexed control mode is enabled and supported."""
        return self.client.control_mode and self._control_mode_supported

    async def get_control_connection(self) -> "ControlConnection":
        """Acquire a multiplexed control connection for this sprite."""
        from .control import get_control_connection

        return await get_control_connection(self)

    async def close_control_connection(self) -> None:
        """Close this sprite's control pool on the current event loop."""
        from .control import close_control_connection

        await close_control_connection(self)

    def has_control_connection(self) -> bool:
        """Return whether this client and sprite own a control connection."""
        from .control import has_control_connection

        return has_control_connection(self)


def _parse_time(value: Any) -> Optional[datetime]:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return None


def _checkpoint_from_dict(data: Dict[str, Any]) -> Checkpoint:
    return Checkpoint(
        id=data.get("id", ""),
        create_time=_parse_time(data.get("create_time")) or datetime.now(),
        comment=data.get("comment"),
        history=data.get("history"),
    )


def _parse_messages(text: str) -> List[StreamMessage]:
    messages = []
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        messages.append(
            StreamMessage(
                type=data.get("type", ""),
                data=data.get("data"),
                error=data.get("error"),
            )
        )
    return messages
