from __future__ import annotations

import json

import httpx
import pytest

from sprites import NetworkPolicy, PolicyRule, SpritesClient, URLSettings
from sprites.exceptions import ExitError, NotFoundError
from sprites.exec import Cmd


def test_destroy_and_delete_delegate_to_client_destroy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SpritesClient("test-token", base_url="https://api.test")
    sprite = client.sprite("demo")
    calls = []

    def destroy_sprite(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(client, "destroy_sprite", destroy_sprite)

    sprite.destroy()
    sprite.delete()

    assert calls == ["demo", "demo"]


def test_update_helpers_delegate_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SpritesClient("test-token", base_url="https://api.test")
    sprite = client.sprite("demo")
    settings = URLSettings(auth="public", private_access="admins")
    calls = []

    def update_url_settings(name: str, passed_settings: URLSettings) -> None:
        calls.append(("url", name, passed_settings))

    def update_sprite(name: str, **kwargs):
        calls.append(("sprite", name, kwargs))
        return "updated"

    monkeypatch.setattr(client, "update_url_settings", update_url_settings)
    monkeypatch.setattr(client, "update_sprite", update_sprite)

    sprite.update_url_settings(settings)
    result = sprite.update(url_settings=settings, labels=["sdk"])

    assert result == "updated"
    assert calls == [
        ("url", "demo", settings),
        (
            "sprite",
            "demo",
            {"url_settings": settings, "labels": ["sdk"]},
        ),
    ]


def test_upgrade_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SpritesClient("test-token", base_url="https://api.test")
    sprite = client.sprite("demo")
    calls = []

    monkeypatch.setattr(client, "upgrade_sprite", lambda name: calls.append(name))

    sprite.upgrade()

    assert calls == ["demo"]


def test_list_sessions_parses_session_metadata(make_mock_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/sprites/demo/exec"
        return httpx.Response(
            200,
            json={
                "sessions": [
                    {
                        "id": "sess-1",
                        "command": "bash",
                        "workdir": "/app",
                        "created": "2026-01-12T21:24:42Z",
                        "bytes_per_second": 42,
                        "is_active": True,
                        "tty": True,
                        "last_activity": "2026-01-12T21:25:42Z",
                    }
                ]
            },
        )

    client = make_mock_client(handler)

    sessions = client.sprite("demo").list_sessions()

    assert len(sessions) == 1
    assert sessions[0].id == "sess-1"
    assert sessions[0].tty is True
    assert sessions[0].last_activity is not None


def test_list_and_get_checkpoints_parse_and_encode_paths(make_mock_client) -> None:
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        encoded_path = (
            str(request.url).split("?", 1)[0].removeprefix("https://api.test")
        )
        seen_paths.append(encoded_path)
        if request.url.path == "/v1/sprites/demo/checkpoints":
            assert request.url.params["history"] == "ancestors"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "checkpoint one",
                        "create_time": "2026-01-12T21:24:42Z",
                        "comment": "before change",
                        "history": "ancestors",
                    }
                ],
            )

        assert encoded_path == "/v1/sprites/demo/checkpoints/checkpoint%20one"
        return httpx.Response(
            200,
            json={
                "id": "checkpoint one",
                "create_time": "2026-01-12T21:24:42Z",
                "comment": "before change",
                "history": "ancestors",
            },
        )

    client = make_mock_client(handler)
    sprite = client.sprite("demo")

    checkpoints = sprite.list_checkpoints(history_filter="ancestors")
    checkpoint = sprite.get_checkpoint("checkpoint one")

    assert checkpoints[0].id == "checkpoint one"
    assert checkpoint.comment == "before change"
    assert seen_paths == [
        "/v1/sprites/demo/checkpoints",
        "/v1/sprites/demo/checkpoints/checkpoint%20one",
    ]


def test_get_checkpoint_raises_not_found(make_mock_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="missing")

    client = make_mock_client(handler)

    with pytest.raises(NotFoundError):
        client.sprite("demo").get_checkpoint("missing")


def test_network_policy_round_trip(make_mock_client) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "rules": [
                        {"domain": "example.com", "action": "allow"},
                        {"include": "defaults"},
                    ]
                },
            )

        assert request.method == "POST"
        assert json.loads(request.content) == {
            "rules": [
                {"domain": "example.org", "action": "deny"},
                {"include": "defaults"},
            ]
        }
        return httpx.Response(204)

    client = make_mock_client(handler)
    sprite = client.sprite("demo")

    policy = sprite.get_network_policy()
    sprite.update_network_policy(
        NetworkPolicy(
            rules=[
                PolicyRule(domain="example.org", action="deny"),
                PolicyRule(include="defaults"),
            ]
        )
    )

    assert policy.rules[0].domain == "example.com"
    assert policy.rules[1].include == "defaults"
    assert calls == [
        ("GET", "/v1/sprites/demo/policy/network"),
        ("POST", "/v1/sprites/demo/policy/network"),
    ]


def test_get_delete_and_signal_service_requests(make_mock_client) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        encoded_path = str(request.url).removeprefix("https://api.test")
        calls.append((request.method, encoded_path, request.content))
        if request.method == "GET":
            assert encoded_path == "/v1/sprites/demo/services/web%2Fapi"
            return httpx.Response(
                200,
                json={
                    "name": "web/api",
                    "cmd": "python",
                    "args": ["-m", "http.server"],
                    "needs": [],
                    "http_port": 8000,
                    "state": {"name": "web/api", "status": "running"},
                },
            )
        if request.method == "DELETE":
            assert encoded_path == "/v1/sprites/demo/services/web%2Fapi"
            return httpx.Response(204)

        assert request.method == "POST"
        assert request.url.path == "/v1/sprites/demo/services/signal"
        assert json.loads(request.content) == {"name": "web/api", "signal": "SIGTERM"}
        return httpx.Response(204)

    client = make_mock_client(handler)
    sprite = client.sprite("demo")

    service = sprite.get_service("web/api")
    sprite.delete_service("web/api")
    sprite.signal_service("web/api", "SIGTERM")

    assert service.name == "web/api"
    assert [method for method, _, _ in calls] == ["GET", "DELETE", "POST"]


def test_run_returns_completed_process_with_captured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_sync(cmd: Cmd) -> int:
        cmd._stdout_data = b"out"
        cmd._stderr_data = b"err"
        return 0

    monkeypatch.setattr(Cmd, "_run_sync", run_sync)
    sprite = SpritesClient("test-token", base_url="https://api.test").sprite("demo")

    result = sprite.run("echo", "hi", capture_output=True, tty=True, tty_rows=40)

    assert result.args == ["echo", "hi"]
    assert result.returncode == 0
    assert result.stdout == b"out"
    assert result.stderr == b"err"


def test_run_check_raises_exit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Cmd, "_run_sync", lambda cmd: 2)
    sprite = SpritesClient("test-token", base_url="https://api.test").sprite("demo")

    with pytest.raises(ExitError) as exc_info:
        sprite.run("false", check=True)

    assert exc_info.value.exit_code() == 2
