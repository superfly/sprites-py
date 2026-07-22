"""
Type definitions for the Sprites SDK
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ClientOptions:
    """Client configuration options."""
    base_url: str = "https://api.sprites.dev"
    timeout: float = 30.0


@dataclass
class URLSettings:
    """URL authentication settings."""
    auth: Optional[str] = None  # "public" or "sprite"
    private_access: Optional[str] = None


@dataclass
class SpriteConfig:
    """Sprite configuration options for creation."""
    ram_mb: Optional[int] = None
    cpus: Optional[int] = None
    region: Optional[str] = None
    storage_gb: Optional[int] = None


@dataclass
class SpawnOptions:
    """Options for spawning a command."""
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    tty: bool = False
    rows: int = 24
    cols: int = 80
    detachable: bool = False
    session_id: Optional[str] = None
    control_mode: bool = False


@dataclass
class ExecOptions(SpawnOptions):
    """Options for exec methods."""
    encoding: str = "utf-8"
    max_buffer: int = 10 * 1024 * 1024  # 10MB


@dataclass
class ExecResult:
    """Result from exec methods."""
    stdout: bytes
    stderr: bytes
    exit_code: int


@dataclass
class SpriteInfo:
    """Sprite information from the API."""
    id: str
    name: str
    organization: str
    status: str
    config: Optional[SpriteConfig] = None
    environment: Optional[Dict[str, str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    bucket_name: Optional[str] = None
    primary_region: Optional[str] = None
    url: Optional[str] = None
    url_settings: Optional[URLSettings] = None
    version: Optional[str] = None
    environment_version: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    last_running_at: Optional[datetime] = None
    last_warming_at: Optional[datetime] = None


@dataclass
class ListOptions:
    """Options for listing sprites."""
    prefix: Optional[str] = None
    max_results: Optional[int] = None
    continuation_token: Optional[str] = None
    bulk_load: bool = False


@dataclass
class SpriteList:
    """Paginated list of sprites."""
    sprites: List[SpriteInfo]
    has_more: bool
    next_continuation_token: Optional[str] = None
    running: int = 0
    warm: int = 0
    cold: int = 0


@dataclass
class Session:
    """Execution session information."""
    id: str
    command: str
    workdir: str
    created: datetime
    bytes_per_second: float
    is_active: bool
    tty: bool
    last_activity: Optional[datetime] = None


@dataclass
class Checkpoint:
    """Checkpoint information."""
    id: str
    create_time: datetime
    comment: Optional[str] = None
    history: Optional[List[str]] = None


@dataclass
class StreamMessage:
    """Streaming message from checkpoint/restore operations."""
    type: str  # "info", "stdout", "stderr", "error"
    data: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PortMapping:
    """Port mapping for proxy operations."""
    local_port: int
    remote_port: int
    remote_host: str = "localhost"


@dataclass
class Service:
    """Service definition."""
    name: str
    cmd: str
    args: List[str] = field(default_factory=list)
    needs: List[str] = field(default_factory=list)
    http_port: Optional[int] = None
    env: Dict[str, str] = field(default_factory=dict)
    dir: Optional[str] = None


@dataclass
class ServiceState:
    """Service state information."""
    name: str
    status: str  # "stopped", "starting", "running", "stopping", "failed"
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    error: Optional[str] = None
    restart_count: int = 0
    next_restart_at: Optional[datetime] = None


@dataclass
class ServiceWithState(Service):
    """Service with its current state."""
    state: Optional[ServiceState] = None


@dataclass
class ServiceRequest:
    """Request body for creating/updating a service."""
    cmd: str
    args: Optional[List[str]] = None
    needs: Optional[List[str]] = None
    http_port: Optional[int] = None
    env: Optional[Dict[str, str]] = None
    dir: Optional[str] = None


@dataclass
class ServiceLogEvent:
    """Service log event from NDJSON stream."""
    type: str  # "stdout", "stderr", "exit", "error", "complete", "started", "stopping", "stopped"
    data: Optional[str] = None
    exit_code: Optional[int] = None
    timestamp: int = 0
    log_files: Optional[Dict[str, str]] = None


@dataclass
class PolicyRule:
    """Network policy rule."""
    domain: Optional[str] = None
    action: Optional[str] = None  # "allow" or "deny"
    include: Optional[str] = None


@dataclass
class NetworkPolicy:
    """Network policy document."""
    rules: List[PolicyRule] = field(default_factory=list)


# Filesystem types

@dataclass
class FileStat:
    """File/directory statistics."""
    name: str
    path: str
    size: int
    mode: str
    mod_time: datetime
    is_dir: bool

    @property
    def is_file(self) -> bool:
        return not self.is_dir


@dataclass
class DirEntry:
    """Directory entry information."""
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mode: str = "0644"
    mod_time: Optional[datetime] = None

    @property
    def is_file(self) -> bool:
        return not self.is_dir


@dataclass
class FSListResponse:
    """Response from /fs/list endpoint."""
    path: str
    entries: List[DirEntry]
    count: int


@dataclass
class FSWriteResponse:
    """Response from /fs/write endpoint."""
    path: str
    size: int
    mode: str


@dataclass
class FSDeleteResponse:
    """Response from /fs/delete endpoint."""
    deleted: List[str]
    count: int


@dataclass
class FSRenameResponse:
    """Response from /fs/rename endpoint."""
    source: str
    dest: str


@dataclass
class FSCopyResponse:
    """Response from /fs/copy endpoint."""
    source: str
    dest: str
    count: int


@dataclass
class FSChmodResponse:
    """Response from /fs/chmod endpoint."""
    path: str
    mode: str
    count: int
