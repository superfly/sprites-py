"""Regression tests for command WebSocket completion semantics."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Union

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from sprites import ExecError, NetworkError, SpritesClient
from sprites.websocket import StreamID

Message = Union[str, bytes, BaseException]


class FakeWebSocket:
    """Small async-iterator stand-in for a connected WebSocket."""

    def __init__(
        self,
        messages: list[Message],
        *,
        close_code: int = 1000,
        close_reason: str = "",
    ) -> None:
        self._messages: Iterator[Message] = iter(messages)
        self.close_code = close_code
        self.close_reason = close_reason
        self.sent: list[bytes] = []
        self.closed = False

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> str | bytes:
        try:
            message = next(self._messages)
        except StopIteration:
            raise StopAsyncIteration from None
        if isinstance(message, BaseException):
            raise message
        return message

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


def command_with_websocket(
    monkeypatch: pytest.MonkeyPatch,
    websocket: FakeWebSocket,
    *,
    tty: bool = False,
):
    """Create a command whose WebSocket dial returns ``websocket``."""

    async def connect(*args, **kwargs):
        return websocket

    monkeypatch.setattr("sprites.websocket.websockets.connect", connect)
    client = SpritesClient("test-token", base_url="https://api.test")
    return client.sprite("demo").command("echo", "test", tty=tty)


def test_dial_failure_is_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def connect(*args, **kwargs):
        raise OSError("host unreachable")

    monkeypatch.setattr("sprites.websocket.websockets.connect", connect)
    client = SpritesClient("test-token", base_url="https://api.test")
    cmd = client.sprite("demo").command("echo", "test")

    with pytest.raises(NetworkError, match="OSError: host unreachable"):
        cmd.output()


def test_normal_close_without_exit_is_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [bytes([StreamID.STDOUT]) + b"partial output\n"],
        close_code=1000,
    )
    cmd = command_with_websocket(monkeypatch, websocket)

    with pytest.raises(
        NetworkError,
        match="closed before receiving command exit status.*code=1000",
    ):
        cmd.output()

    assert cmd._stdout_data == b"partial output\n"
    assert cmd._stderr_data == b""
    assert websocket.closed is True


def test_abnormal_close_without_exit_is_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close = Close(1011, "abnormal")
    websocket = FakeWebSocket(
        [ConnectionClosedError(close, None)],
        close_code=1011,
        close_reason="abnormal",
    )
    cmd = command_with_websocket(monkeypatch, websocket)

    with pytest.raises(
        NetworkError,
        match="code=1011.*reason='abnormal'",
    ):
        cmd.output()


def test_nonzero_exit_frame_remains_exec_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket(
        [
            bytes([StreamID.STDERR]) + b"command failed\n",
            bytes([StreamID.EXIT, 7]),
        ]
    )
    cmd = command_with_websocket(monkeypatch, websocket)

    with pytest.raises(ExecError) as exc_info:
        cmd.output()

    assert exc_info.value.exit_code() == 7
    assert exc_info.value.stderr == b"command failed\n"


def test_zero_exit_frame_returns_output(monkeypatch: pytest.MonkeyPatch) -> None:
    websocket = FakeWebSocket(
        [
            bytes([StreamID.STDOUT]) + b"test\n",
            bytes([StreamID.EXIT, 0]),
        ]
    )
    cmd = command_with_websocket(monkeypatch, websocket)

    assert cmd.output() == b"test\n"


def test_tty_exit_message_sets_process_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = FakeWebSocket([b"terminal output\n", '{"type":"exit","exit_code":3}'])
    cmd = command_with_websocket(monkeypatch, websocket, tty=True)

    with pytest.raises(ExecError) as exc_info:
        cmd.output()

    assert exc_info.value.exit_code() == 3
    assert exc_info.value.stdout == b"terminal output\n"
