"""Native asyncio command execution for Sprites."""

from __future__ import annotations

from ._interfaces import SpriteLike
from .exceptions import ExitError
from .exec import CompletedProcess, _CmdBase


class AsyncCmd(_CmdBase):
    """An asynchronously executed command.

    The command runs directly on the caller's active event loop. Instances are
    created by :meth:`AsyncSprite.command` rather than constructed directly.
    """

    async def _execute(self) -> int:
        if self._started:
            raise RuntimeError("command already started")
        self._started = True
        try:
            self._exit_code = await self._run_async()
            return self._exit_code
        finally:
            self._finished = True

    async def run(self) -> None:
        """Start the command and wait for it to complete.

        Raises:
            ExitError: If the command exits with a non-zero status.
            NetworkError: If the WebSocket fails before an exit status arrives.
            TimeoutError: If the configured timeout expires.
        """
        code = await self._execute()
        if code != 0:
            raise ExitError(
                f"exit status {code}", code, self._stdout_data, self._stderr_data
            )

    async def output(self) -> bytes:
        """Run the command and return stdout.

        Returns:
            Bytes written to stdout.

        Raises:
            ExitError: If the command exits with a non-zero status.
            RuntimeError: If stdout is already configured.
        """
        if self.stdout is not None:
            raise RuntimeError("stdout already set")
        self._capture_stdout = True
        code = await self._execute()
        if code != 0:
            raise ExitError(
                f"exit status {code}", code, self._stdout_data, self._stderr_data
            )
        return self._stdout_data

    async def combined_output(self) -> bytes:
        """Run the command and return stdout followed by stderr.

        Returns:
            Combined stdout and stderr bytes.

        Raises:
            ExitError: If the command exits with a non-zero status.
            RuntimeError: If stdout or stderr is already configured.
        """
        if self.stdout is not None:
            raise RuntimeError("stdout already set")
        if self.stderr is not None:
            raise RuntimeError("stderr already set")
        self._capture_stdout = True
        self._capture_stderr = True
        code = await self._execute()
        combined = self._stdout_data + self._stderr_data
        if code != 0:
            raise ExitError(f"exit status {code}", code, combined, b"")
        return combined


async def run(
    sprite: SpriteLike,
    *args: str,
    capture_output: bool = False,
    timeout: float | None = None,
    check: bool = False,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    tty: bool = False,
    tty_rows: int = 24,
    tty_cols: int = 80,
) -> CompletedProcess:
    """Run a command asynchronously, mirroring :func:`subprocess.run`.

    Args:
        sprite: Sprite on which to execute the command.
        *args: Command and arguments.
        capture_output: Capture stdout and stderr in the result.
        timeout: Maximum execution time in seconds.
        check: Raise :class:`ExitError` for a non-zero exit status.
        env: Environment variables for the command.
        cwd: Working directory for the command.
        tty: Whether to allocate a pseudo-terminal.
        tty_rows: Terminal height in rows.
        tty_cols: Terminal width in columns.

    Returns:
        Completed command information.
    """
    cmd = AsyncCmd(
        sprite,
        list(args),
        env=env,
        cwd=cwd,
        tty=tty,
        tty_rows=tty_rows,
        tty_cols=tty_cols,
        timeout=timeout,
    )
    if capture_output:
        cmd._capture_stdout = True
        cmd._capture_stderr = True

    code = await cmd._execute()
    result = CompletedProcess(
        args=list(args),
        returncode=code,
        stdout=cmd._stdout_data if capture_output else None,
        stderr=cmd._stderr_data if capture_output else None,
    )
    if check and code != 0:
        raise ExitError(
            f"exit status {code}", code, result.stdout or b"", result.stderr or b""
        )
    return result
