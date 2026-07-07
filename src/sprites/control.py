"""Control connection for multiplexed operations over a single WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, Optional, Callable
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed

from sprites._utils import quote_path_segment, websocket_base_url

if TYPE_CHECKING:
    from .sprite import Sprite

# Control envelope protocol constants (must match server's pkg/wss)
CONTROL_PREFIX = "control:"
TYPE_OP_START = "op.start"
TYPE_OP_COMPLETE = "op.complete"
TYPE_OP_ERROR = "op.error"

# WebSocket keepalive timeouts
WS_PING_INTERVAL = 15  # seconds
WS_PONG_WAIT = 45  # seconds


class StreamID:
    """Stream identifiers for the binary protocol."""
    STDIN = 0
    STDOUT = 1
    STDERR = 2
    EXIT = 3
    STDIN_EOF = 4


class OpConn:
    """Represents an active operation on a control connection."""

    def __init__(self, cc: ControlConnection, tty: bool = False):
        """Initialize an operation connection.

        Args:
            cc: Parent control connection
            tty: Whether TTY mode is enabled
        """
        self.cc = cc
        self.tty = tty
        self.closed = False
        self.exit_code = -1
        self._done_event = asyncio.Event()

        # Output buffers
        self._stdout_buffer: bytearray = bytearray()
        self._stderr_buffer: bytearray = bytearray()

        # Callbacks
        self.on_stdout: Optional[Callable[[bytes], None]] = None
        self.on_stderr: Optional[Callable[[bytes], None]] = None
        self.on_message: Optional[Callable[[dict], None]] = None

    async def write(self, data: bytes) -> None:
        """Write data to the operation (stdin).

        Args:
            data: Data to write
        """
        if self.closed:
            raise RuntimeError("Operation closed")

        if self.tty:
            # PTY mode - send raw data
            await self.cc._send_data(data)
        else:
            # Non-PTY mode - prepend stream ID
            message = bytes([StreamID.STDIN]) + data
            await self.cc._send_data(message)

    async def send_eof(self) -> None:
        """Send stdin EOF."""
        if self.closed or self.tty:
            return
        await self.cc._send_data(bytes([StreamID.STDIN_EOF]))

    async def resize(self, cols: int, rows: int) -> None:
        """Send resize control message (TTY only).

        Args:
            cols: Number of columns
            rows: Number of rows
        """
        if not self.tty:
            return
        msg = json.dumps({"type": "resize", "cols": cols, "rows": rows})
        await self.cc._send_text(msg)

    async def signal(self, sig: str) -> None:
        """Send signal to remote process.

        Args:
            sig: Signal name (e.g., "TERM", "INT")
        """
        msg = json.dumps({"type": "signal", "signal": sig})
        await self.cc._send_text(msg)

    def handle_data(self, data: bytes) -> None:
        """Handle incoming data frame.

        Args:
            data: Incoming data
        """
        if self.tty:
            # PTY mode - emit raw output
            self._stdout_buffer.extend(data)
            if self.on_stdout:
                self.on_stdout(data)
        else:
            # Non-PTY mode - parse stream prefix
            if not data:
                return

            stream_id = data[0]
            payload = data[1:]

            if stream_id == StreamID.STDOUT:
                self._stdout_buffer.extend(payload)
                if self.on_stdout:
                    self.on_stdout(payload)
            elif stream_id == StreamID.STDERR:
                self._stderr_buffer.extend(payload)
                if self.on_stderr:
                    self.on_stderr(payload)
            elif stream_id == StreamID.EXIT:
                # Store exit code but DON'T signal done yet
                # Wait for op.complete message to ensure proper sequencing
                self.exit_code = payload[0] if payload else 0

    def handle_text(self, data: str) -> None:
        """Handle text message (session_info, notifications, etc.).

        Args:
            data: Text message data
        """
        try:
            msg = json.loads(data)
            if self.on_message:
                self.on_message(msg)
        except json.JSONDecodeError:
            pass

    def complete(self, exit_code: Optional[int] = None) -> None:
        """Mark operation as complete.

        Args:
            exit_code: Optional exit code
        """
        if self.closed:
            return
        self.closed = True
        if exit_code is not None:
            self.exit_code = exit_code
        self._done_event.set()

    def close(self) -> None:
        """Close the operation."""
        if self.closed:
            return
        self.closed = True
        self._done_event.set()

    def is_closed(self) -> bool:
        """Check if operation is closed."""
        return self.closed

    def get_exit_code(self) -> int:
        """Get exit code (-1 if not exited)."""
        return self.exit_code

    async def wait(self) -> int:
        """Wait for operation to complete.

        Returns:
            Exit code
        """
        if self.closed:
            return self.exit_code
        await self._done_event.wait()
        return self.exit_code

    def get_stdout(self) -> bytes:
        """Get accumulated stdout buffer."""
        return bytes(self._stdout_buffer)

    def get_stderr(self) -> bytes:
        """Get accumulated stderr buffer."""
        return bytes(self._stderr_buffer)


class ControlConnection:
    """Manages a persistent WebSocket connection for multiplexed operations."""

    def __init__(self, sprite: Sprite):
        """Initialize a control connection.

        Args:
            sprite: The sprite this connection is for
        """
        self.sprite = sprite
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.op_active = False
        self.op_conn: OpConn | None = None
        self.closed = False
        self.close_error: Optional[Exception] = None
        self._read_task: Optional[asyncio.Task[None]] = None

    async def connect(self) -> None:
        """Connect to the control endpoint."""
        if self.ws is not None:
            raise RuntimeError("Already connected")

        base_url = websocket_base_url(self.sprite.client.base_url)
        sprite_name = quote_path_segment(self.sprite.name)
        url = f"{base_url}/v1/sprites/{sprite_name}/control"
        headers = {"Authorization": f"Bearer {self.sprite.client.token}"}

        self.ws = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=WS_PING_INTERVAL,
            ping_timeout=WS_PONG_WAIT,
            close_timeout=2,  # Faster close handshake for clean shutdown
            max_size=10 * 1024 * 1024,  # 10MB
        )

        # Start read loop
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Read messages from WebSocket."""
        if self.ws is None:
            return

        try:
            async for message in self.ws:
                await self._handle_message(message)
        except ConnectionClosed as e:
            self.close_error = e
        except Exception as e:
            self.close_error = e
        finally:
            self.closed = True
            if self.op_conn is not None:
                self.op_conn.close()

    async def _handle_message(self, message: str | bytes) -> None:
        """Handle incoming WebSocket message.

        Args:
            message: Incoming message
        """
        # Check for control message
        if isinstance(message, str) and message.startswith(CONTROL_PREFIX):
            payload = message[len(CONTROL_PREFIX):]
            try:
                msg = json.loads(payload)
                self._handle_control_message(msg)
            except json.JSONDecodeError:
                pass
            return

        # Data frame - deliver to active operation
        if self.op_conn is not None:
            if isinstance(message, str):
                self.op_conn.handle_text(message)
            else:
                self.op_conn.handle_data(message)

    def _handle_control_message(self, msg: Dict[str, Any]) -> None:
        """Handle control envelope message.

        Args:
            msg: Parsed control message
        """
        msg_type = msg.get("type", "")

        if msg_type == TYPE_OP_COMPLETE:
            if self.op_conn is not None:
                exit_code = msg.get("args", {}).get("exitCode", 0)
                self.op_conn.complete(exit_code)
            self.op_active = False
            self.op_conn = None

        elif msg_type == TYPE_OP_ERROR:
            if self.op_conn is not None:
                error = msg.get("args", {}).get("error", "unknown error")
                # Store error in stderr buffer
                self.op_conn._stderr_buffer.extend(f"Error: {error}\n".encode())
                self.op_conn.complete()
            self.op_active = False
            self.op_conn = None

    async def start_op(
        self,
        op: str,
        cmd: Optional[list[str]] = None,
        env: Optional[Dict[str, str]] = None,
        dir: Optional[str] = None,
        tty: bool = False,
        rows: int = 24,
        cols: int = 80,
        stdin: bool = True,
    ) -> OpConn:
        """Start a new operation.

        Args:
            op: Operation name (e.g., "exec")
            cmd: Command and arguments
            env: Environment variables
            dir: Working directory
            tty: Enable TTY mode
            rows: TTY rows
            cols: TTY columns
            stdin: Whether stdin is expected

        Returns:
            OpConn for the operation
        """
        if self.closed:
            raise RuntimeError(f"Control connection closed: {self.close_error}")

        # Note: op_active is now managed by the pool, so we don't check it here
        # The pool ensures only one caller has this connection at a time

        if self.ws is None:
            raise RuntimeError("WebSocket not connected")
        op_conn = OpConn(self, tty)
        self.op_conn = op_conn

        # Build args for the control message
        args: Dict[str, Any] = {}
        if cmd:
            args["cmd"] = cmd
        if env:
            env_list = [f"{k}={v}" for k, v in env.items()]
            args["env"] = env_list
        if dir:
            args["dir"] = dir
        if tty:
            args["tty"] = "true"
            args["rows"] = str(rows)
            args["cols"] = str(cols)
        args["stdin"] = "true" if stdin else "false"

        # Send op.start
        ctrl_msg = {
            "type": TYPE_OP_START,
            "op": op,
            "args": args,
        }
        frame = CONTROL_PREFIX + json.dumps(ctrl_msg)
        await self.ws.send(frame)

        return op_conn

    async def _send_data(self, data: bytes) -> None:
        """Send data frame.

        Args:
            data: Data to send
        """
        if self.ws is None or self.ws.state != websockets.protocol.State.OPEN:
            raise RuntimeError("WebSocket not connected")
        await self.ws.send(data)

    async def _send_text(self, data: str) -> None:
        """Send text frame.

        Args:
            data: Text to send
        """
        if self.ws is None or self.ws.state != websockets.protocol.State.OPEN:
            raise RuntimeError("WebSocket not connected")
        await self.ws.send(data)

    async def close(self) -> None:
        """Close the control connection.

        Proper close sequence per websockets library documentation:
        1. Close the websocket (causes read loop to exit via ConnectionClosed)
        2. Wait for the close to complete with wait_closed()
        3. Wait for read task to finish naturally
        """
        if self.op_conn is not None:
            self.op_conn.close()

        # Close websocket first - this will cause the read loop to exit
        # with ConnectionClosed exception, allowing proper cleanup
        ws = self.ws
        if ws is not None:
            try:
                await ws.close()
                # wait_closed() ensures all internal tasks (like keepalive) are done
                await ws.wait_closed()
            except Exception:
                pass

        # Now wait for read task to finish naturally (it will exit due to close)
        if self._read_task is not None:
            try:
                # Wait with timeout in case read task is stuck
                await asyncio.wait_for(self._read_task, timeout=2.0)
            except asyncio.TimeoutError:
                # If it doesn't finish, cancel as fallback
                self._read_task.cancel()
                try:
                    await self._read_task
                except asyncio.CancelledError:
                    pass
            except Exception:
                pass
            self._read_task = None

        self.ws = None
        self.closed = True

    def is_closed(self) -> bool:
        """Check if connection is closed."""
        return self.closed


# Pool configuration (matches Go SDK)
MAX_POOL_SIZE = 100  # Sanity cap - checkout fails if pool is full
POOL_DRAIN_THRESHOLD = 20  # When release and size > this, drain idle conns
POOL_DRAIN_TARGET = 10  # Drain down to this many conns when draining


class ControlPool:
    """Manages a pool of control connections for concurrent operations."""

    def __init__(self, sprite: Sprite, max_size: int = MAX_POOL_SIZE):
        """Initialize a control pool.

        Args:
            sprite: The sprite to connect to
            max_size: Maximum number of connections in the pool (default 100)
        """
        self.sprite = sprite
        self.max_size = max_size
        self.conns: list[ControlConnection] = []
        self.waiters: list[asyncio.Future[ControlConnection]] = []
        self.closed = False
        self._lock = asyncio.Lock()

    async def acquire(self) -> ControlConnection:
        """Acquire a connection from the pool.

        Creates a new connection if the pool isn't full, otherwise waits.

        Returns:
            ControlConnection that is ready for use
        """
        async with self._lock:
            if self.closed:
                raise RuntimeError("Pool is closed")

            # Try to find an available connection
            for cc in self.conns:
                if not cc.is_closed() and not cc.op_active:
                    cc.op_active = True  # Mark as in use
                    return cc

            # If pool isn't full, create a new connection
            if len(self.conns) < self.max_size:
                cc = ControlConnection(self.sprite)
                await cc.connect()
                self.conns.append(cc)
                cc.op_active = True  # Mark as in use
                return cc

            # Pool is full, wait for a connection
            waiter: asyncio.Future[ControlConnection] = asyncio.get_event_loop().create_future()
            self.waiters.append(waiter)

        # Wait outside the lock
        return await waiter

    def release(self, cc: ControlConnection) -> None:
        """Release a connection back to the pool.

        Args:
            cc: The connection to release
        """
        cc.op_active = False
        cc.op_conn = None

        # If there are waiters, give them this connection
        if self.waiters:
            waiter = self.waiters.pop(0)
            cc.op_active = True  # Mark as in use again
            waiter.set_result(cc)
            return

        # Try to drain idle connections if pool is large
        self._try_drain()

    def _try_drain(self) -> None:
        """Drain idle connections when pool is large.

        When pool size exceeds POOL_DRAIN_THRESHOLD, close idle connections
        down to POOL_DRAIN_TARGET.
        """
        if self.closed or len(self.conns) <= POOL_DRAIN_THRESHOLD:
            return

        # Find idle connections (not active, not closed)
        idle_conns = [
            cc for cc in self.conns
            if not cc.op_active and not cc.is_closed()
        ]

        # Sort by least recently used (we don't track last_used, so just take from end)
        to_close = len(self.conns) - POOL_DRAIN_TARGET
        if to_close <= 0:
            return

        # Close idle connections
        closed = 0
        for cc in idle_conns:
            if closed >= to_close:
                break
            # Close async in background
            asyncio.create_task(cc.close())
            self.conns.remove(cc)
            closed += 1

    async def close(self) -> None:
        """Close all connections in the pool."""
        async with self._lock:
            self.closed = True

            # Cancel all waiters
            for waiter in self.waiters:
                waiter.cancel()
            self.waiters = []

            # Close all connections
            for cc in self.conns:
                await cc.close()
            self.conns = []

    def size(self) -> int:
        """Return the current number of connections in the pool."""
        return len(self.conns)

    def has_connections(self) -> bool:
        """Return True if the pool has any active connections."""
        return len(self.conns) > 0


# Module-level cache for control pools (one pool per sprite)
_control_pools: Dict[str, ControlPool] = {}


async def get_control_connection(sprite: Sprite) -> ControlConnection:
    """Get a control connection from the pool for a sprite.

    Args:
        sprite: The sprite to connect to

    Returns:
        ControlConnection instance (caller must release when done)
    """
    key = f"{sprite.client.base_url}:{sprite.name}"

    # Get or create pool
    if key not in _control_pools:
        _control_pools[key] = ControlPool(sprite)

    pool = _control_pools[key]
    return await pool.acquire()


def release_control_connection(sprite: Sprite, cc: ControlConnection) -> None:
    """Release a control connection back to the pool.

    Args:
        sprite: The sprite whose pool to release to
        cc: The connection to release
    """
    key = f"{sprite.client.base_url}:{sprite.name}"

    if key in _control_pools:
        _control_pools[key].release(cc)


async def close_control_connection(sprite: Sprite) -> None:
    """Close the control pool for a sprite.

    Args:
        sprite: The sprite whose pool to close
    """
    key = f"{sprite.client.base_url}:{sprite.name}"

    if key in _control_pools:
        pool = _control_pools.pop(key)
        await pool.close()


def has_control_connection(sprite: Sprite) -> bool:
    """Check if a sprite has any active control connections.

    Args:
        sprite: The sprite to check

    Returns:
        True if the sprite has active control connections
    """
    key = f"{sprite.client.base_url}:{sprite.name}"
    if key not in _control_pools:
        return False
    return _control_pools[key].has_connections()


async def _close_all_pools() -> None:
    """Close all control pools. Called on program exit."""
    pools = list(_control_pools.values())
    _control_pools.clear()
    for pool in pools:
        try:
            await pool.close()
        except Exception:
            pass  # Ignore errors during cleanup

    # Give background tasks time to clean up
    await asyncio.sleep(0.1)


def _cleanup_on_exit() -> None:
    """Cleanup handler called on program exit."""
    if not _control_pools:
        return

    try:
        from sprites.loop import get_loop, stop_loop

        loop = get_loop()
        future = asyncio.run_coroutine_threadsafe(_close_all_pools(), loop)
        future.result(timeout=5)

        # Stop the event loop thread
        stop_loop()
    except Exception:
        pass  # Ignore errors during cleanup


# Register cleanup handler
import atexit
atexit.register(_cleanup_on_exit)
