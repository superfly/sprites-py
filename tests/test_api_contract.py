from __future__ import annotations

import pytest
import httpx
import json
import asyncio

from sprites import ListOptions, SpritesClient, URLSettings
from sprites.exceptions import TimeoutError
from sprites.exec import Cmd


def make_client(handler):
    client = SpritesClient("test-token", base_url="https://api.test")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_list_sprites_parses_current_snake_case_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["bulk_load"] == "true"
        return httpx.Response(
            200,
            json={
                "sprites": [
                    {
                        "id": "sprite-1",
                        "name": "demo",
                        "organization": "acme",
                        "status": "running",
                        "url": "https://demo.sprites.app",
                        "url_settings": {"auth": "sprite", "private_access": "admins"},
                        "version": "0.0.1",
                        "environment_version": "0.0.2",
                        "labels": ["sdk"],
                        "created_at": "2026-01-12T21:24:42Z",
                        "updated_at": "2026-01-12T21:25:42Z",
                    }
                ],
                "has_more": True,
                "next_continuation_token": "next",
                "running": 1,
                "warm": 2,
                "cold": 3,
            },
        )

    client = make_client(handler)

    result = client.list_sprites(ListOptions(bulk_load=True))

    assert result.has_more is True
    assert result.next_continuation_token == "next"
    assert (result.running, result.warm, result.cold) == (1, 2, 3)
    sprite = result.sprites[0]
    assert sprite.organization == "acme"
    assert sprite.url_settings is not None
    assert sprite.url_settings.private_access == "admins"
    assert sprite.labels == ["sdk"]
    assert sprite.created_at is not None


def test_create_sprite_sends_current_optional_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["url_settings"] == {"auth": "public", "private_access": "admins"}
        assert body["labels"] == ["sdk"]
        assert body["wait_for_capacity"] is True
        assert body["runtime"] == "dev"
        return httpx.Response(
            201,
            json={
                "id": "sprite-1",
                "name": "demo",
                "organization": "acme",
                "status": "cold",
                "url_settings": {"auth": "public", "private_access": "admins"},
            },
        )

    client = make_client(handler)

    sprite = client.create_sprite(
        "demo",
        url_settings=URLSettings(auth="public", private_access="admins"),
        labels=["sdk"],
        wait_for_capacity=True,
        runtime="dev",
    )

    assert sprite.name == "demo"
    assert sprite.id == "sprite-1"
    assert sprite.url_settings is not None
    assert sprite.url_settings.auth == "public"


def test_update_sprite_can_update_labels_and_url_settings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/v1/sprites/demo"
        body = json.loads(request.content)
        assert body["labels"] == ["sdk", "python"]
        assert body["url_settings"] == {"auth": "sprite"}
        return httpx.Response(
            200,
            json={"name": "demo", "labels": ["sdk", "python"], "url_settings": {"auth": "sprite"}},
        )

    client = make_client(handler)

    sprite = client.update_sprite(
        "demo",
        labels=["sdk", "python"],
        url_settings=URLSettings(auth="sprite"),
    )

    assert sprite.labels == ["sdk", "python"]


def test_destroy_sprite_uses_delete_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/v1/sprites/demo"
        return httpx.Response(204)

    client = make_client(handler)

    client.destroy_sprite("demo")


def test_service_helpers_parse_api_array_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sprites/demo/services"
        return httpx.Response(
            200,
            json=[
                {
                    "name": "web",
                    "cmd": "python",
                    "args": ["-m", "http.server"],
                    "needs": [],
                    "http_port": 8000,
                    "state": {
                        "name": "web",
                        "status": "running",
                        "pid": 123,
                        "started_at": "2026-01-12T21:24:42Z",
                        "restart_count": 1,
                    },
                }
            ],
        )

    client = make_client(handler)

    services = client.sprite("demo").list_services()

    assert len(services) == 1
    assert services[0].name == "web"
    assert services[0].state is not None
    assert services[0].state.status == "running"
    assert services[0].state.started_at is not None


def test_sprite_command_accepts_documented_tty_options() -> None:
    sprite = SpritesClient("test-token").sprite("demo")

    cmd = sprite.command("bash", tty=True, tty_rows=40, tty_cols=120)

    assert isinstance(cmd, Cmd)
    assert cmd.tty is True
    assert cmd.tty_rows == 40
    assert cmd.tty_cols == 120


def test_command_timeout_raises_sdk_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_command(_cmd: Cmd) -> int:
        await asyncio.sleep(1)
        return 0

    monkeypatch.setattr("sprites.websocket.run_ws_command", slow_command)
    sprite = SpritesClient("test-token").sprite("demo")
    cmd = Cmd(sprite, ["sleep"], timeout=0.01)

    with pytest.raises(TimeoutError):
        asyncio.run(cmd._run_async())
