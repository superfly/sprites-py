"""WebSocket protocol handler for Sprites command execution."""

from __future__ import annotations

import asyncio
import json
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidStatusCode

from sprites._signals import signal_headers
from sprites._utils import quote_path_segment, websocket_base_url
from sprites.exceptions import parse_api_error

if TYPE_CHECKING:
    from sprites.exec import Cmd


class StreamID(IntEnum):
    """Stream identifiers for the binary protocol."""

    STDIN = 0
    STDOUT = 1
    STDERR = 2
    EXIT = 3
    STDIN_EOF = 4


# WebSocket keepalive timeouts (matching Go SDK)
WS_PING_INTERVAL = 15  # seconds
WS_PONG_WAIT = 45  # seconds


class WSCommand:
    """WebSocket command execution handler."""

    def __init__(self, cmd: Cmd):
        """Initialize a WebSocket command handler.

        Args:
            cmd: The Cmd instance to execute.
        """
        self.cmd = cmd
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.exit_code = -1
        self.started = False
        self.done = False
        self._is_attach = cmd.session_id is not None
        self.text_message_handler: Callable[[bytes], None] | None = None
        self._stdout_buffer: bytearray = bytearray()
        self._stderr_buffer: bytearray = bytearray()
        self._io_task: asyncio.Task[None] | None = None
        self._session_info_event = asyncio.Event()

    def _build_websocket_url(self) -> str:
        """Build the WebSocket URL with query parameters."""
        base_url = websocket_base_url(self.cmd.sprite.client.base_url)

        # Build path
        sprite_name = quote_path_segment(self.cmd.sprite.name)
        if self.cmd.session_id:
            session_id = quote_path_segment(self.cmd.session_id)
            path = f"/v1/sprites/{sprite_name}/exec/{session_id}"
        else:
            path = f"/v1/sprites/{sprite_name}/exec"

        # Build query params
        params: list[tuple[str, str]] = []

        # Command args (only for new commands)
        if not self.cmd.session_id:
            for arg in self.cmd.args:
                params.append(("cmd", arg))
            if self.cmd.args:
                params.append(("path", self.cmd.args[0]))

        # Environment variables
        for key, value in self.cmd.env.items():
            params.append(("env", f"{key}={value}"))

        # Working directory
        if self.cmd.dir:
            params.append(("dir", self.cmd.dir))

        # TTY settings
        if self.cmd.tty:
            params.append(("tty", "true"))
            params.append(("rows", str(self.cmd.tty_rows)))
            params.append(("cols", str(self.cmd.tty_cols)))

        # Stdin indicator - always true for now
        params.append(("stdin", "true"))

        query = urlencode(params)
        return f"{base_url}{path}?{query}"

    async def start(self) -> None:
        """Start the WebSocket connection."""
        if self.started:
            raise RuntimeError("already started")
        self.started = True

        url = self._build_websocket_url()
        headers = {
            "Authorization": f"Bearer {self.cmd.sprite.client.token}",
            **signal_headers(),
        }

        try:
            self.ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=WS_PING_INTERVAL,
                ping_timeout=WS_PONG_WAIT,
                max_size=10 * 1024 * 1024,  # 10MB max message size
                # The server holds the WS open for ~5s after sending EXIT
                # before initiating its own close. The Elixir SDK doesn't
                # wait at all — it sends a CLOSE frame and tears the TCP.
                # Mirror that: close_timeout=0 sends CLOSE without awaiting
                # the server's reciprocal frame, dropping per-exec latency
                # from ~5.3s to ~140ms (a ~38x speedup). See #24.
                close_timeout=0,
            )
        except InvalidStatusCode as e:
            # Try to parse as a structured API error
            body = b""
            response_headers: dict[str, str] = {}
            if hasattr(e, "response") and e.response is not None:
                # websockets >= 12.0 provides response object
                if hasattr(e.response, "body"):
                    body = e.response.body or b""
                if hasattr(e.response, "headers"):
                    response_headers = dict(e.response.headers)
            api_err = parse_api_error(e.status_code, body, response_headers)
            if api_err is not None:
                raise api_err from None
            # Fall back to original exception
            raise

        # Start I/O loop in background IMMEDIATELY after connect
        # This must happen before any other awaits to avoid missing messages
        self._io_task = asyncio.create_task(self._run_io())
        # Yield to let the I/O task start reading before we return
        await asyncio.sleep(0)

        # When attaching to an existing session, wait for session_info to determine TTY mode
        if self._is_attach:
            await self._wait_for_session_info()

    async def _wait_for_session_info(self) -> None:
        """Wait for session_info message when attaching."""
        try:
            await asyncio.wait_for(self._session_info_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            raise RuntimeError("timeout waiting for session_info") from None

    async def _run_io(self) -> None:
        """Main I/O loop."""
        if self.ws is None:
            return

        try:
            # Handle stdin in background if provided
            stdin_task: asyncio.Task[None] | None = None
            eof_task: asyncio.Task[None] | None = None
            if self.cmd.stdin is not None:
                stdin_task = asyncio.create_task(self._copy_stdin())
            else:
                # Send EOF as a background task - don't block before reading
                eof_task = asyncio.create_task(self._send_stdin_eof())

            # Process incoming messages - start reading immediately
            # EOF task will run concurrently when we yield on message receive
            async for message in self.ws:
                await self._handle_message(message)
                # Exit loop when EXIT message received
                if self.done:
                    break

        except ConnectionClosed as e:
            # Check if this is a normal closure (code 1000)
            # The websockets library can sometimes raise ConnectionClosed even for normal closures
            if e.code == 1000:
                # Normal closure - treat as success if no exit code received
                if self.exit_code < 0:
                    self.exit_code = 0
            else:
                # Non-normal closure - treat as error
                error_msg = (
                    f"WebSocket ConnectionClosed: code={e.code}, reason={e.reason}\n"
                )
                self._stderr_buffer.extend(error_msg.encode())
                if self.exit_code < 0:
                    self.exit_code = 1
        except Exception as e:
            # Any other exception - treat as error
            error_msg = f"WebSocket I/O error: {type(e).__name__}: {e}\n"
            self._stderr_buffer.extend(error_msg.encode())
            if self.exit_code < 0:
                self.exit_code = 1
        else:
            # Loop completed normally (connection closed with code 1000)
            if self.exit_code < 0:
                self.exit_code = 0
        finally:
            self.done = True
            # Clean up stdin task
            if stdin_task is not None:
                stdin_task.cancel()
                try:
                    await stdin_task
                except asyncio.CancelledError:
                    pass
            # Ensure EOF task completed (don't cancel - it should finish quickly)
            if eof_task is not None and not eof_task.done():
                try:
                    await eof_task
                except Exception:
                    pass

    async def _handle_message(self, message: str | bytes) -> None:
        """Handle incoming WebSocket message."""
        if self.cmd.tty:
            # TTY mode
            if isinstance(message, str):
                self._handle_text_message(message)
            else:
                # Binary - raw terminal data
                self._stdout_buffer.extend(message)
                if self.cmd.stdout is not None:
                    self.cmd.stdout.write(message)
        else:
            # Non-TTY mode - stream-based protocol
            if isinstance(message, str):
                self._handle_text_message(message)
                return

            if not message:
                return

            stream_id = message[0]
            payload = message[1:]

            if stream_id == StreamID.STDOUT:
                self._stdout_buffer.extend(payload)
                if self.cmd.stdout is not None:
                    self.cmd.stdout.write(payload)
            elif stream_id == StreamID.STDERR:
                self._stderr_buffer.extend(payload)
                if self.cmd.stderr is not None:
                    self.cmd.stderr.write(payload)
            elif stream_id == StreamID.EXIT:
                self.exit_code = payload[0] if payload else 0
                # Mark as done - the connection will close and loop will exit
                self.done = True

    def _handle_text_message(self, message: str) -> None:
        """Handle text control/notification messages."""
        try:
            info = json.loads(message)
            if info.get("type") == "session_info":
                self.cmd.tty = info.get("tty", False)
                self._session_info_event.set()
        except json.JSONDecodeError:
            pass

        if self.text_message_handler:
            self.text_message_handler(message.encode())

    async def _copy_stdin(self) -> None:
        """Copy data from stdin to WebSocket."""
        if self.cmd.stdin is None:
            return

        try:
            loop = asyncio.get_event_loop()
            while True:
                # Read stdin in executor to avoid blocking
                data = await loop.run_in_executor(None, self.cmd.stdin.read, 4096)
                if not data:
                    break
                await self._write_stdin(data)
            await self._send_stdin_eof()
        except Exception:
            pass

    async def _write_stdin(self, data: bytes) -> None:
        """Write data to stdin stream."""
        if self.ws is None:
            return

        if self.cmd.tty:
            await self.ws.send(data)
        else:
            message = bytes([StreamID.STDIN]) + data
            await self.ws.send(message)

    async def _send_stdin_eof(self) -> None:
        """Send stdin EOF marker."""
        if self.ws is None:
            return

        if not self.cmd.tty:
            await self.ws.send(bytes([StreamID.STDIN_EOF]))

    async def resize(self, cols: int, rows: int) -> None:
        """Send resize control message."""
        if not self.cmd.tty or self.ws is None:
            return
        msg = json.dumps({"type": "resize", "cols": cols, "rows": rows})
        await self.ws.send(msg)

    async def wait(self) -> int:
        """Wait for command to complete and return exit code."""
        if self._io_task is not None:
            try:
                await self._io_task
            except Exception as e:
                # Task failed unexpectedly
                error_msg = f"WebSocket task failed: {type(e).__name__}: {e}\n"
                self._stderr_buffer.extend(error_msg.encode())
                if self.exit_code < 0:
                    self.exit_code = 1
        # Safeguard: exit_code should never be -1 at this point
        if self.exit_code < 0:
            error_msg = "WebSocket error: exit code not set\n"
            self._stderr_buffer.extend(error_msg.encode())
            self.exit_code = 1
        return self.exit_code

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    def get_stdout(self) -> bytes:
        """Get the accumulated stdout buffer."""
        return bytes(self._stdout_buffer)

    def get_stderr(self) -> bytes:
        """Get the accumulated stderr buffer."""
        return bytes(self._stderr_buffer)


async def run_ws_command(cmd: Cmd) -> int:
    """Run a command via WebSocket and return exit code.

    Args:
        cmd: The command to execute.

    Returns:
        The exit code of the command.
    """
    # Use control mode if enabled (except for attach operations)
    if cmd.session_id is None and cmd.sprite.use_control_mode():
        return await run_ws_command_via_control(cmd)

    ws_cmd = WSCommand(cmd)
    ws_cmd.text_message_handler = cmd._text_message_handler

    try:
        await ws_cmd.start()
        exit_code = await ws_cmd.wait()
    except Exception as e:
        # If connection or I/O fails, store error message in stderr buffer
        # and return error exit code
        error_msg = f"WebSocket error: {type(e).__name__}: {e}\n"
        ws_cmd._stderr_buffer.extend(error_msg.encode())
        exit_code = 1
    finally:
        # Ensure connection is closed
        await ws_cmd.close()

    # Copy buffered output if cmd is capturing
    if cmd._capture_stdout:
        cmd._stdout_data = ws_cmd.get_stdout()
    if cmd._capture_stderr:
        cmd._stderr_data = ws_cmd.get_stderr()
    # Always copy stderr on error for debugging, even if not explicitly capturing
    elif exit_code != 0:
        cmd._stderr_data = ws_cmd.get_stderr()

    return exit_code


async def _run_ws_command_direct(cmd: Cmd) -> int:
    """Run a command via direct WebSocket (no control mode).

    Args:
        cmd: The command to execute.

    Returns:
        The exit code of the command.
    """
    ws_cmd = WSCommand(cmd)
    ws_cmd.text_message_handler = cmd._text_message_handler

    try:
        await ws_cmd.start()
        exit_code = await ws_cmd.wait()
    except Exception as e:
        error_msg = f"WebSocket error: {type(e).__name__}: {e}\n"
        ws_cmd._stderr_buffer.extend(error_msg.encode())
        exit_code = 1
    finally:
        await ws_cmd.close()

    # Copy buffered output if cmd is capturing
    if cmd._capture_stdout:
        cmd._stdout_data = ws_cmd.get_stdout()
    if cmd._capture_stderr:
        cmd._stderr_data = ws_cmd.get_stderr()
    elif exit_code != 0:
        cmd._stderr_data = ws_cmd.get_stderr()

    return exit_code


async def run_ws_command_via_control(cmd: Cmd) -> int:
    """Run a command via the control connection for multiplexed operations.

    Args:
        cmd: The command to execute.

    Returns:
        The exit code of the command.
    """
    from sprites.control import get_control_connection, release_control_connection

    cc = None
    try:
        # Double-check control mode is still supported (may have been disabled
        # by another concurrent command that already got a 404)
        if not cmd.sprite._control_mode_supported:
            return await _run_ws_command_direct(cmd)

        # Get a control connection from the pool
        cc = await get_control_connection(cmd.sprite)

        # Build operation arguments
        args: dict[str, Any] = {"cmd": cmd.args}

        # Add environment variables (pass dict - start_op converts to list)
        if cmd.env:
            args["env"] = cmd.env

        # Add working directory
        if cmd.dir:
            args["dir"] = cmd.dir

        # Add TTY settings
        if cmd.tty:
            args["tty"] = True
            args["rows"] = cmd.tty_rows
            args["cols"] = cmd.tty_cols

        # Add stdin indicator
        args["stdin"] = cmd.stdin is not None

        # Start the exec operation
        op = await cc.start_op("exec", **args)

        # Handle stdin
        if cmd.stdin is not None:
            loop = asyncio.get_event_loop()
            try:
                while True:
                    data = await loop.run_in_executor(None, cmd.stdin.read, 4096)
                    if not data:
                        break
                    await op.write(data)
            except Exception:
                pass
            await op.send_eof()
        else:
            await op.send_eof()

        # Wait for operation to complete
        exit_code = await op.wait()

        # Copy output
        cmd._stdout_data = op.get_stdout()
        cmd._stderr_data = op.get_stderr()

        return exit_code

    except (InvalidStatusCode, InvalidStatus):
        # Control endpoint returned error (likely 404) - fall back to direct mode
        # Release connection if we got one
        if cc is not None:
            release_control_connection(cmd.sprite, cc)
            cc = None
        # Mark sprite as not supporting control mode to avoid repeated failures
        cmd.sprite._control_mode_supported = False
        # Retry with direct WebSocket
        return await _run_ws_command_direct(cmd)

    except Exception as e:
        # If control mode fails for other reasons, store error message in stderr buffer
        error_msg = f"Control mode error: {type(e).__name__}: {e}\n"
        cmd._stderr_data = error_msg.encode()
        return 1
    finally:
        # Always release the connection back to the pool
        if cc is not None:
            release_control_connection(cmd.sprite, cc)
