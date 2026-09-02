from __future__ import annotations

import asyncio
from types import SimpleNamespace

import sprites.control as control_module
import sprites.loop as loop_module


def test_control_pools_are_scoped_to_their_event_loop(monkeypatch) -> None:
    registered = []
    created = []

    class FakePool:
        def __init__(self, sprite) -> None:
            self.sprite = sprite
            self.connection = object()
            created.append(self)

        async def acquire(self):
            return self.connection

    sprite = SimpleNamespace(
        name="demo",
        client=SimpleNamespace(base_url="https://api.test"),
    )
    monkeypatch.setattr(control_module, "_control_pools", {})
    monkeypatch.setattr(control_module, "_cleanup_registered", False)
    monkeypatch.setattr(control_module, "ControlPool", FakePool)
    monkeypatch.setattr(control_module.atexit, "register", registered.append)

    first = asyncio.run(control_module.get_control_connection(sprite))
    second = asyncio.run(control_module.get_control_connection(sprite))

    assert first is not second
    assert len(created) == 2
    assert len(control_module._control_pools) == 1
    assert next(iter(control_module._control_pools))[0].is_closed()
    assert registered == [control_module._cleanup_on_exit]


def test_get_existing_loop_never_creates_a_loop(monkeypatch) -> None:
    monkeypatch.setattr(loop_module, "_loop", None)

    def fail_new_event_loop():
        raise AssertionError("get_existing_loop() created an event loop")

    monkeypatch.setattr(loop_module.asyncio, "new_event_loop", fail_new_event_loop)

    assert loop_module.get_existing_loop() is None


def test_control_cleanup_does_not_recreate_a_stopped_loop(monkeypatch) -> None:
    monkeypatch.setattr(loop_module, "_loop", None)
    monkeypatch.setattr(loop_module, "_thread", None)
    monkeypatch.setattr(control_module, "_control_pools", {"remaining": object()})

    def fail_get_loop():
        raise AssertionError("control cleanup called the creating loop accessor")

    def fail_new_event_loop():
        raise AssertionError("control cleanup created an event loop")

    def fail_thread(*args, **kwargs):
        raise AssertionError("control cleanup created a thread")

    monkeypatch.setattr(loop_module, "get_loop", fail_get_loop)
    monkeypatch.setattr(loop_module.asyncio, "new_event_loop", fail_new_event_loop)
    monkeypatch.setattr(loop_module.threading, "Thread", fail_thread)

    control_module._cleanup_on_exit()

    assert loop_module._loop is None
    assert loop_module._thread is None


def test_control_cleanup_closes_pools_while_loop_is_running(monkeypatch) -> None:
    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    loop = loop_module.get_loop()
    assert loop.is_running()
    pool = FakePool()
    pools = {(loop, 1, "https://api.test", "demo"): pool}
    monkeypatch.setattr(control_module, "_control_pools", pools)

    control_module._cleanup_on_exit()

    assert pool.closed is True
    assert pools == {}
    assert loop_module.get_existing_loop() is None
