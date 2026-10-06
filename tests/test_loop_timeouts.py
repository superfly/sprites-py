"""Consistent synchronous deadlines across Python versions and competing timers."""

import asyncio
import builtins
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import patch

import pytest

from sprites import Sprite, SpritesClient
from sprites.exceptions import SpriteError
from sprites.exceptions import TimeoutError as SpriteTimeoutError
from sprites.loop import run_sync, stop_loop


@pytest.fixture(autouse=True)
def cleanup_loop():
    yield
    stop_loop()


def test_sdk_timeout_is_also_a_builtin_timeout():
    error = SpriteTimeoutError("command timed out")
    assert isinstance(error, SpriteError)
    assert isinstance(error, builtins.TimeoutError)
    assert str(error) == "command timed out"


def test_caller_deadline_cancels_the_coroutine():
    cancelled = threading.Event()

    async def hang():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(SpriteTimeoutError, match="timed out after 0.05s"):
        run_sync(hang(), timeout=0.05)
    assert cancelled.wait(1), "deadline left the background coroutine running"


@pytest.mark.parametrize(
    "error",
    [
        SpriteTimeoutError("inner deadline"),
        builtins.TimeoutError("inner timeout"),
        ValueError("failure"),
    ],
)
def test_coroutine_errors_are_preserved(error):
    async def fail():
        raise error

    with pytest.raises(type(error)) as raised:
        run_sync(fail(), timeout=1)
    # asyncio may copy a built-in timeout while chaining the task to the future.
    assert str(raised.value) == str(error)
    if type(error) is not builtins.TimeoutError:
        assert raised.value is error


def test_completion_after_deadline_does_not_leak_an_empty_timeout():
    # A result can arrive between future.result's deadline and the exception handler.
    future = Future()
    deadline = FutureTimeoutError()

    def result(timeout):
        future.set_result(42)
        raise deadline

    async def unused():
        return 42

    coro = unused()
    try:
        with (
            patch("sprites.loop.asyncio.run_coroutine_threadsafe", return_value=future),
            patch.object(future, "result", result),
        ):
            with pytest.raises(SpriteTimeoutError, match="timed out") as raised:
                run_sync(coro, timeout=0.01)
        assert raised.value.__cause__ is deadline
    finally:
        coro.close()


def test_command_timer_race_always_raises_sdk_timeout(monkeypatch):
    async def hang(command):
        await asyncio.Event().wait()

    monkeypatch.setattr("sprites.websocket.run_ws_command", hang)
    with SpritesClient(token="test-token") as client:
        sprite = Sprite(name="test-sprite", client=client)
        for _ in range(30):
            with pytest.raises(SpriteTimeoutError, match="timed out"):
                sprite.run("sleep", "30", timeout=0.01)
