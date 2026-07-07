"""
Sprite class representing a sprite instance
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional
from datetime import datetime
import httpx

from .types import (
    SpriteConfig,
    URLSettings,
    Checkpoint,
    Session,
    NetworkPolicy,
    PolicyRule,
    ServiceWithState,
)
from .exceptions import (
    SpriteError,
    NetworkError,
    NotFoundError,
)
from ._utils import parse_sprite_info, quote_path_segment, sprite_base_url

if TYPE_CHECKING:
    from .client import SpritesClient
    from .filesystem import SpriteFilesystem
    from .control import ControlConnection


class Sprite:
    """Represents a sprite instance."""

    def __init__(self, name: str, client: "SpritesClient"):
        """
        Initialize a Sprite instance.

        Args:
            name: Sprite name
            client: SpritesClient instance
        """
        self.name = name
        self.client = client

        # Control mode support flag (set to False when 404 is received)
        self._control_mode_supported: bool = True

        # Additional properties from API
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
        """Update sprite properties from API response."""
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
        """Get default headers with authorization."""
        return {
            "Authorization": f"Bearer {self.client.token}",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        """Get sprite-specific base URL."""
        return sprite_base_url(self.client.base_url, self.name)

    # ========== Filesystem API ==========

    def filesystem(self, working_dir: str = "/") -> "SpriteFilesystem":
        """
        Get a filesystem interface for the sprite.

        Args:
            working_dir: Working directory to use as root (default: "/")

        Returns:
            SpriteFilesystem instance that supports pathlib.Path-like operations
        """
        from .filesystem import SpriteFilesystem
        return SpriteFilesystem(self, working_dir)

    # ========== Lifecycle API ==========

    def destroy(self) -> None:
        """Destroy this sprite."""
        self.client.destroy_sprite(self.name)

    def delete(self) -> None:
        """Alias for destroy(), named after the HTTP DELETE method."""
        self.destroy()

    def upgrade(self) -> None:
        """Upgrade this sprite to the latest version."""
        self.client.upgrade_sprite(self.name)

    def update_url_settings(self, settings: URLSettings) -> None:
        """
        Update URL authentication settings.

        This is a compatibility convenience for updating only URL settings.
        Prefer update(...) when changing mutable sprite fields.

        Args:
            settings: URL settings with auth: "public" for no auth, "sprite" for authenticated
        """
        self.client.update_url_settings(self.name, settings)

    def update(
        self,
        *,
        url_settings: Optional[URLSettings] = None,
        labels: Optional[List[str]] = None,
    ) -> "Sprite":
        """Partially update mutable settings and return the refreshed sprite."""
        return self.client.update_sprite(
            self.name,
            url_settings=url_settings,
            labels=labels,
        )

    # ========== Sessions API ==========

    def list_sessions(self) -> List[Session]:
        """
        List active sessions.

        Returns:
            List of Session objects
        """
        try:
            response = self.client._client.get(
                f"{self._base_url()}/exec",
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error listing sessions: {e}")

        if not response.is_success:
            raise SpriteError(
                f"Failed to list sessions (status {response.status_code}): {response.text}"
            )

        result = response.json()
        sessions: List[Session] = []

        for s in result.get("sessions", []):
            last_activity = None
            if s.get("last_activity"):
                try:
                    last_activity = datetime.fromisoformat(
                        s["last_activity"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            created = datetime.now()
            if s.get("created"):
                try:
                    created = datetime.fromisoformat(
                        s["created"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            sessions.append(Session(
                id=s.get("id", ""),
                command=s.get("command", ""),
                workdir=s.get("workdir", ""),
                created=created,
                bytes_per_second=s.get("bytes_per_second", 0),
                is_active=s.get("is_active", False),
                tty=s.get("tty", False),
                last_activity=last_activity,
            ))

        return sessions

    # ========== Checkpoint API ==========

    def list_checkpoints(self, history_filter: Optional[str] = None) -> List[Checkpoint]:
        """
        List checkpoints.

        Args:
            history_filter: Optional filter for checkpoint history

        Returns:
            List of Checkpoint objects
        """
        url = f"{self._base_url()}/checkpoints"
        params = {}
        if history_filter:
            params["history"] = history_filter

        try:
            response = self.client._client.get(
                url,
                headers=self._headers(),
                params=params if params else None,
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error listing checkpoints: {e}")

        if not response.is_success:
            raise SpriteError(
                f"Failed to list checkpoints (status {response.status_code}): {response.text}"
            )

        raw = response.json()
        checkpoints: List[Checkpoint] = []

        for cp in raw:
            create_time = datetime.now()
            if cp.get("create_time"):
                try:
                    create_time = datetime.fromisoformat(
                        cp["create_time"].replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

            checkpoints.append(Checkpoint(
                id=cp.get("id", ""),
                create_time=create_time,
                comment=cp.get("comment"),
                history=cp.get("history"),
            ))

        return checkpoints

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """
        Get checkpoint details.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            Checkpoint object
        """
        try:
            response = self.client._client.get(
                f"{self._base_url()}/checkpoints/{quote_path_segment(checkpoint_id)}",
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error getting checkpoint: {e}")

        if response.status_code == 404:
            raise NotFoundError(f"Checkpoint not found: {checkpoint_id}")

        if not response.is_success:
            raise SpriteError(
                f"Failed to get checkpoint (status {response.status_code}): {response.text}"
            )

        cp = response.json()
        create_time = datetime.now()
        if cp.get("create_time"):
            try:
                create_time = datetime.fromisoformat(
                    cp["create_time"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        return Checkpoint(
            id=cp.get("id", ""),
            create_time=create_time,
            comment=cp.get("comment"),
            history=cp.get("history"),
        )

    def create_checkpoint(self, comment: str = ""):
        """
        Create a new checkpoint.

        Args:
            comment: Optional comment for the checkpoint

        Returns:
            Iterator of checkpoint creation messages
        """
        from .checkpoint import create_checkpoint
        return create_checkpoint(self, comment)

    def restore_checkpoint(self, checkpoint_id: str):
        """
        Restore a checkpoint.

        Args:
            checkpoint_id: Checkpoint ID to restore

        Returns:
            Iterator of restore messages
        """
        from .checkpoint import restore_checkpoint
        return restore_checkpoint(self, checkpoint_id)

    # ========== Command Execution API ==========

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
    ):
        """
        Create a command to run on this sprite.

        Args:
            *args: Command and arguments
            env: Environment variables
            cwd: Working directory
            timeout: Command timeout in seconds
            stdin: Optional file-like stdin source
            stdout: Optional file-like stdout sink
            stderr: Optional file-like stderr sink
            tty: Enable TTY mode
            tty_rows: Terminal height
            tty_cols: Terminal width

        Returns:
            Cmd object for executing the command
        """
        from .exec import Cmd
        return Cmd(
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

    def run(
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
    ):
        """Run a command on this sprite, mirroring subprocess.run.

        Use command(...) when you need streaming stdin/stdout/stderr handles.
        """
        from .exec import run

        return run(
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
        self,
        session_id: str,
        timeout: Optional[float] = None,
    ):
        """
        Attach to an existing session.

        Args:
            session_id: Session ID to attach to
            timeout: Command timeout in seconds

        Returns:
            Cmd object for the attached session
        """
        from .exec import Cmd
        return Cmd(
            sprite=self,
            args=[],
            session_id=session_id,
            timeout=timeout,
        )

    # ========== Services API ==========

    def list_services(self) -> List[ServiceWithState]:
        """
        List all services on this sprite.

        Returns:
            List of ServiceWithState objects
        """
        from .services import list_services
        return list_services(self)

    def get_service(self, service_name: str) -> ServiceWithState:
        """
        Get a specific service.

        Args:
            service_name: Service name

        Returns:
            ServiceWithState object
        """
        from .services import get_service
        return get_service(self, service_name)

    def delete_service(self, service_name: str) -> None:
        """
        Delete a service.

        Args:
            service_name: Service name
        """
        try:
            response = self.client._client.delete(
                f"{self._base_url()}/services/{quote_path_segment(service_name)}",
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error deleting service: {e}")

        if response.status_code != 204 and not response.is_success:
            raise SpriteError(
                f"Failed to delete service (status {response.status_code}): {response.text}"
            )

    def create_service(
        self,
        service_name: str,
        cmd: str,
        args: Optional[List[str]] = None,
        needs: Optional[List[str]] = None,
        http_port: Optional[int] = None,
        duration: Optional[float] = None,
    ):
        """Create or update a service and return its log stream."""
        from .services import create_service
        return create_service(self, service_name, cmd, args, needs, http_port, duration)

    def start_service(self, service_name: str, duration: Optional[float] = None):
        """Start a service and return its log stream."""
        from .services import start_service
        return start_service(self, service_name, duration)

    def stop_service(self, service_name: str, timeout: Optional[float] = None):
        """Stop a service and return its log stream."""
        from .services import stop_service
        return stop_service(self, service_name, timeout)

    def signal_service(self, service_name: str, signal: str) -> None:
        """Send a signal to a running service."""
        from .services import signal_service
        signal_service(self, service_name, signal)

    # ========== Policy API ==========

    def get_network_policy(self) -> NetworkPolicy:
        """
        Get the current network policy.

        Returns:
            NetworkPolicy object
        """
        try:
            response = self.client._client.get(
                f"{self._base_url()}/policy/network",
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error getting network policy: {e}")

        if not response.is_success:
            raise SpriteError(
                f"Failed to get network policy (status {response.status_code}): {response.text}"
            )

        data = response.json()
        rules: List[PolicyRule] = []

        for r in data.get("rules", []):
            rules.append(PolicyRule(
                domain=r.get("domain"),
                action=r.get("action"),
                include=r.get("include"),
            ))

        return NetworkPolicy(rules=rules)

    def update_network_policy(self, policy: NetworkPolicy) -> None:
        """
        Update the network policy.

        Args:
            policy: NetworkPolicy object
        """
        rules = []
        for r in policy.rules:
            rule: Dict[str, Any] = {}
            if r.domain:
                rule["domain"] = r.domain
            if r.action:
                rule["action"] = r.action
            if r.include:
                rule["include"] = r.include
            rules.append(rule)

        try:
            response = self.client._client.post(
                f"{self._base_url()}/policy/network",
                headers=self._headers(),
                json={"rules": rules},
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error updating network policy: {e}")

        if not response.is_success:
            raise SpriteError(
                f"Failed to update network policy (status {response.status_code}): {response.text}"
            )

    # ========== Control Connection API ==========

    def use_control_mode(self) -> bool:
        """Check if control mode is enabled for this sprite.

        Returns:
            True if control mode is enabled and supported by this sprite
        """
        return self.client.control_mode and self._control_mode_supported

    async def get_control_connection(self) -> "ControlConnection":
        """Get or create a control connection for multiplexed operations.

        Returns:
            ControlConnection instance
        """
        from .control import get_control_connection
        return await get_control_connection(self)

    async def close_control_connection(self) -> None:
        """Close the control connection if open."""
        from .control import close_control_connection
        await close_control_connection(self)

    def has_control_connection(self) -> bool:
        """Check if this sprite has an active control connection.

        This can be used to verify that control mode is being used.

        Returns:
            True if a control connection pool exists with active connections
        """
        from .control import has_control_connection
        return has_control_connection(self)
