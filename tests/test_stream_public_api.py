from __future__ import annotations

import httpx

import sprites.checkpoint as checkpoint_module
import sprites.services as services_module
from sprites import SpritesClient
from sprites.checkpoint import CheckpointStream, RestoreStream
from sprites.services import ServiceStream


def test_checkpoint_and_restore_streams_skip_invalid_lines() -> None:
    checkpoint_response = httpx.Response(
        200,
        text='not json\n{"type":"progress","data":{"step":1}}\n\n{"type":"done"}\n',
    )
    restore_response = httpx.Response(
        200,
        text='{"type":"restoring"}\ninvalid\n{"type":"done","error":null}\n',
    )

    checkpoint_messages = list(CheckpointStream(checkpoint_response))
    restore_messages = list(RestoreStream(restore_response))

    assert [message.type for message in checkpoint_messages] == ["progress", "done"]
    assert checkpoint_messages[0].data == {"step": 1}
    assert [message.type for message in restore_messages] == ["restoring", "done"]


def test_create_and_restore_checkpoint_post_and_parse_streams(
    monkeypatch,
) -> None:
    captured = []
    responses = [
        httpx.Response(
            200, text='{"type":"progress","data":"saving"}\n{"type":"done"}\n'
        ),
        httpx.Response(
            200, text='{"type":"progress","data":"restoring"}\n{"type":"done"}\n'
        ),
    ]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            captured.append((url, kwargs))
            return responses.pop(0)

    monkeypatch.setattr(checkpoint_module.httpx, "Client", FakeClient)
    sprite = SpritesClient("test-token", base_url="https://api.test").sprite(
        "demo/name"
    )

    create_messages = list(sprite.create_checkpoint("before upgrade"))
    restore_messages = list(sprite.restore_checkpoint("checkpoint one"))

    assert [message.type for message in create_messages] == ["progress", "done"]
    assert [message.type for message in restore_messages] == ["progress", "done"]
    assert captured[0] == (
        "https://api.test/v1/sprites/demo%2Fname/checkpoint",
        {
            "json": {"comment": "before upgrade"},
            "headers": {"Content-Type": "application/json"},
        },
    )
    assert captured[1] == (
        "https://api.test/v1/sprites/demo%2Fname/checkpoints/checkpoint%20one/restore",
        {},
    )


def test_service_stream_process_all() -> None:
    stream = ServiceStream(
        [
            services_module.ServiceLogEvent(type="log", data="first"),
            services_module.ServiceLogEvent(type="exit", exit_code=0),
        ]
    )
    handled = []

    stream.process_all(handled.append)

    assert [event.type for event in handled] == ["log", "exit"]


def test_create_start_and_stop_service_post_and_parse_streams(monkeypatch) -> None:
    captured = []
    responses = [
        httpx.Response(
            200, text='{"type":"log","data":"created"}\n{"type":"exit","exit_code":0}\n'
        ),
        httpx.Response(200, text='{"type":"log","data":"started"}\n'),
        httpx.Response(200, text='{"type":"log","data":"stopped"}\n'),
    ]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def put(self, url, **kwargs):
            captured.append(("PUT", url, kwargs))
            return responses.pop(0)

        def post(self, url, **kwargs):
            captured.append(("POST", url, kwargs))
            return responses.pop(0)

    monkeypatch.setattr(services_module.httpx, "Client", FakeClient)
    sprite = SpritesClient("test-token", base_url="https://api.test").sprite(
        "demo/name"
    )

    create_events = list(
        sprite.create_service(
            "web api",
            "python",
            args=["-m", "http.server"],
            needs=["db"],
            http_port=8000,
            duration=1.5,
            env={"APP_ENV": "test"},
            dir="/app",
        )
    )
    start_events = list(sprite.start_service("web api", duration=2.0))
    stop_events = list(sprite.stop_service("web api", timeout=3.0))

    assert [event.type for event in create_events] == ["log", "exit"]
    assert create_events[1].exit_code == 0
    assert start_events[0].data == "started"
    assert stop_events[0].data == "stopped"
    assert captured[0] == (
        "PUT",
        "https://api.test/v1/sprites/demo%2Fname/services/web%20api?duration=1.5s",
        {
            "json": {
                "cmd": "python",
                "args": ["-m", "http.server"],
                "needs": ["db"],
                "http_port": 8000,
                "env": {"APP_ENV": "test"},
                "dir": "/app",
            }
        },
    )
    assert captured[1] == (
        "POST",
        "https://api.test/v1/sprites/demo%2Fname/services/web%20api/start?duration=2.0s",
        {},
    )
    assert captured[2] == (
        "POST",
        "https://api.test/v1/sprites/demo%2Fname/services/web%20api/stop?timeout=3.0s",
        {},
    )


def test_create_service_preserves_positional_duration_and_empty_env(
    monkeypatch,
) -> None:
    captured = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def put(self, url, **kwargs):
            captured.append((url, kwargs))
            return httpx.Response(200, text='{"type":"exit","exit_code":0}\n')

    monkeypatch.setattr(services_module.httpx, "Client", FakeClient)
    sprite = SpritesClient("test-token", base_url="https://api.test").sprite("demo")

    list(sprite.create_service("worker", "run", None, None, None, 2.5, env={}))

    assert captured == [
        (
            "https://api.test/v1/sprites/demo/services/worker?duration=2.5s",
            {"json": {"cmd": "run", "env": {}}},
        )
    ]
