from __future__ import annotations

import json

import httpx
import pytest

from sprites import SpritesClient, URLSettings
from sprites.exceptions import AuthenticationError, NotFoundError, SpriteError


def test_context_manager_closes_underlying_http_client() -> None:
    with SpritesClient("test-token", base_url="https://api.test") as client:
        underlying = client._client

    assert underlying.is_closed


def test_sprite_returns_unfetched_handle() -> None:
    client = SpritesClient("test-token", base_url="https://api.test")

    sprite = client.sprite("demo")

    assert sprite.name == "demo"
    assert sprite.client is client


def test_get_sprite_parses_current_fields_and_encodes_name(make_mock_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://api.test/v1/sprites/demo%20space%2Fslash"
        return httpx.Response(
            200,
            json={
                "id": "sprite-1",
                "name": "demo space/slash",
                "organization": "acme",
                "status": "running",
                "url": "https://demo.sprites.app",
                "url_settings": {"auth": "sprite", "private_access": "admins"},
                "version": "1.2.3",
                "environment_version": "4.5.6",
                "labels": ["sdk", "python"],
                "created_at": "2026-01-12T21:24:42Z",
                "updated_at": "2026-01-12T21:25:42Z",
                "last_running_at": "2026-01-12T21:26:42Z",
                "last_warming_at": "2026-01-12T21:27:42Z",
            },
        )

    client = make_mock_client(handler)

    sprite = client.get_sprite("demo space/slash")

    assert sprite.id == "sprite-1"
    assert sprite.organization_name == "acme"
    assert sprite.url_settings is not None
    assert sprite.url_settings.private_access == "admins"
    assert sprite.labels == ["sdk", "python"]
    assert sprite.created_at is not None
    assert sprite.updated_at is not None
    assert sprite.last_running_at is not None
    assert sprite.last_warming_at is not None


def test_list_all_sprites_paginates_and_applies_prefix(make_mock_client) -> None:
    seen_params = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen_params.append(params)
        assert request.url.path == "/v1/sprites"
        assert params["prefix"] == "demo"
        assert params["max_results"] == "100"

        if "continuation_token" not in params:
            return httpx.Response(
                200,
                json={
                    "sprites": [{"name": "demo-1", "status": "running"}],
                    "has_more": True,
                    "next_continuation_token": "next-page",
                },
            )

        assert params["continuation_token"] == "next-page"
        return httpx.Response(
            200,
            json={
                "sprites": [{"name": "demo-2", "status": "cold"}],
                "has_more": False,
            },
        )

    client = make_mock_client(handler)

    sprites = client.list_all_sprites(prefix="demo")

    assert [sprite.name for sprite in sprites] == ["demo-1", "demo-2"]
    assert len(seen_params) == 2


def test_delete_sprite_alias_delegates_to_destroy(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SpritesClient("test-token", base_url="https://api.test")
    calls = []

    def destroy_sprite(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(client, "destroy_sprite", destroy_sprite)

    client.delete_sprite("demo")

    assert calls == ["demo"]


@pytest.mark.parametrize(
    ("status_code", "expected_exception"),
    [
        (401, AuthenticationError),
        (404, NotFoundError),
        (500, SpriteError),
    ],
)
def test_handle_response_maps_api_errors(
    status_code: int,
    expected_exception: type[Exception],
) -> None:
    client = SpritesClient("test-token", base_url="https://api.test")
    response = httpx.Response(status_code, text="boom")

    with pytest.raises(expected_exception):
        client._handle_response(response, "test operation")


def test_create_token_posts_fly_auth_and_invite_code(monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.Client
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"token": "sprite-token"})

    def fake_client(*args, **kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("sprites.client.httpx.Client", fake_client)

    token = SpritesClient.create_token("fly-token", "acme", invite_code="invite-1")

    assert token == "sprite-token"
    assert captured == {
        "url": "https://api.sprites.dev/v1/organizations/acme/tokens",
        "auth": "FlyV1 fly-token",
        "body": {
            "description": "Sprite SDK Token",
            "invite_code": "invite-1",
        },
    }


def test_update_sprite_requires_a_mutable_field() -> None:
    client = SpritesClient("test-token", base_url="https://api.test")

    with pytest.raises(ValueError, match="url_settings or labels is required"):
        client.update_sprite("demo")


def test_update_url_settings_sends_private_access(make_mock_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/v1/sprites/demo"
        assert json.loads(request.content) == {
            "url_settings": {
                "auth": "sprite",
                "private_access": "admins",
            }
        }
        return httpx.Response(204)

    client = make_mock_client(handler)

    client.update_url_settings("demo", URLSettings(auth="sprite", private_access="admins"))
