from __future__ import annotations

import asyncio
import inspect
import json

import httpx
import pytest

import sprites.control as control_module
from sprites import (
    AsyncCmd,
    AsyncSprite,
    AsyncSpriteFilesystem,
    AsyncSpritePath,
    AsyncSpritesClient,
    ListOptions,
    NetworkPolicy,
    PolicyRule,
    Sprite,
    SpriteFilesystem,
    SpritePath,
    SpritesClient,
    URLSettings,
)
from sprites.exceptions import (
    AuthenticationError,
    ExitError,
    NotFoundError,
    TimeoutError,
)
from sprites.exec import Cmd


async def make_async_client(handler) -> AsyncSpritesClient:
    client = AsyncSpritesClient("test-token", base_url="https://api.test")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def public_callables(cls) -> set[str]:
    return {
        name
        for name, value in inspect.getmembers(cls)
        if not name.startswith("_") and (callable(value) or isinstance(value, property))
    }


@pytest.mark.parametrize(
    ("async_class", "sync_class", "async_only", "sync_only"),
    [
        (AsyncSpritesClient, SpritesClient, {"aclose"}, {"close"}),
        (AsyncSprite, Sprite, set(), set()),
        (AsyncSpritePath, SpritePath, set(), set()),
        (AsyncSpriteFilesystem, SpriteFilesystem, set(), set()),
        (AsyncCmd, Cmd, set(), set()),
    ],
)
def test_async_public_api_matches_sync_api(
    async_class, sync_class, async_only: set[str], sync_only: set[str]
) -> None:
    assert public_callables(async_class) - async_only == (
        public_callables(sync_class) - sync_only
    )


@pytest.mark.asyncio
async def test_async_context_manager_closes_underlying_client() -> None:
    async with AsyncSpritesClient("test-token") as client:
        underlying = client._client

    assert underlying.is_closed


@pytest.mark.asyncio
async def test_aclose_closes_only_clients_control_pools(monkeypatch) -> None:
    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    loop = asyncio.get_running_loop()
    client = AsyncSpritesClient("test-token")
    other_client = AsyncSpritesClient("other-token")
    own_pool = FakePool()
    other_pool = FakePool()
    pools = {
        (loop, id(client), client.base_url, "demo"): own_pool,
        (loop, id(other_client), other_client.base_url, "demo"): other_pool,
    }
    monkeypatch.setattr(control_module, "_control_pools", pools)

    try:
        await client.aclose()

        assert own_pool.closed is True
        assert other_pool.closed is False
        assert list(pools) == [(loop, id(other_client), other_client.base_url, "demo")]
    finally:
        await other_client.aclose()


@pytest.mark.asyncio
async def test_async_client_lifecycle_and_pagination() -> None:
    pages = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal pages
        if request.method == "POST":
            assert json.loads(request.content) == {
                "name": "demo",
                "labels": ["async"],
                "url_settings": {"auth": "public"},
            }
            return httpx.Response(201, json={"name": "demo", "status": "cold"})
        if request.method == "DELETE":
            return httpx.Response(204)

        pages += 1
        assert request.url.params["prefix"] == "demo"
        if pages == 1:
            return httpx.Response(
                200,
                json={
                    "sprites": [{"name": "demo-1"}],
                    "has_more": True,
                    "next_continuation_token": "next",
                },
            )
        assert request.url.params["continuation_token"] == "next"
        return httpx.Response(
            200, json={"sprites": [{"name": "demo-2"}], "has_more": False}
        )

    client = await make_async_client(handler)
    try:
        sprite = await client.create_sprite(
            "demo", labels=["async"], url_settings=URLSettings(auth="public")
        )
        assert isinstance(sprite, AsyncSprite)
        assert sprite.status == "cold"

        sprites = await client.list_all_sprites(prefix="demo")
        assert [item.name for item in sprites] == ["demo-1", "demo-2"]
        assert all(isinstance(item, AsyncSprite) for item in sprites)

        await client.destroy_sprite("demo")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_list_sprites_preserves_page_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["bulk_load"] == "true"
        return httpx.Response(
            200,
            json={
                "sprites": [{"name": "demo", "labels": ["async"]}],
                "has_more": False,
                "running": 1,
            },
        )

    client = await make_async_client(handler)
    try:
        page = await client.list_sprites(ListOptions(bulk_load=True))
        assert page.running == 1
        assert page.sprites[0].labels == ["async"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_exception"),
    [(401, AuthenticationError), (404, NotFoundError)],
)
async def test_async_client_maps_api_errors(
    status_code: int, expected_exception: type[Exception]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="boom")

    client = await make_async_client(handler)
    try:
        with pytest.raises(expected_exception):
            await client.get_sprite("demo")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_command_runs_on_callers_loop_without_sync_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running_loop = asyncio.get_running_loop()

    async def run_command(cmd: AsyncCmd) -> int:
        assert asyncio.get_running_loop() is running_loop
        cmd._stdout_data = b"hello\n"
        cmd._exit_code = 0
        return 0

    def fail_sync_bridge(*args, **kwargs):
        raise AssertionError("the sync event-loop bridge must not be used")

    monkeypatch.setattr("sprites.websocket.run_ws_command", run_command)
    monkeypatch.setattr("sprites.loop.run_sync", fail_sync_bridge)

    client = AsyncSpritesClient("test-token")
    try:
        cmd = client.sprite("demo").command("echo", "hello")
        assert isinstance(cmd, AsyncCmd)
        assert await cmd.output() == b"hello\n"
        assert cmd.exit_code == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_command_raises_exit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_command(cmd: AsyncCmd) -> int:
        cmd._stdout_data = b"partial"
        cmd._stderr_data = b"failed"
        return 7

    monkeypatch.setattr("sprites.websocket.run_ws_command", fail_command)
    client = AsyncSpritesClient("test-token")
    try:
        with pytest.raises(ExitError) as exc_info:
            await client.sprite("demo").command("false").output()

        assert exc_info.value.exit_code() == 7
        assert exc_info.value.stdout == b"partial"
        assert exc_info.value.stderr == b"failed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_command_timeout_raises_sdk_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_command(cmd: AsyncCmd) -> int:
        await asyncio.sleep(1)
        return 0

    monkeypatch.setattr("sprites.websocket.run_ws_command", slow_command)
    client = AsyncSpritesClient("test-token")
    try:
        with pytest.raises(TimeoutError):
            await client.sprite("demo").command("sleep", timeout=0.01).run()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_async_filesystem_uses_async_transport_and_path_types() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/fs/write"):
            assert request.content == b"hello"
            return httpx.Response(200)
        if request.url.path.endswith("/fs/read"):
            return httpx.Response(200, content=b"hello")
        if request.url.path.endswith("/fs/list"):
            return httpx.Response(
                200,
                json={
                    "entries": [
                        {
                            "name": "note.txt",
                            "path": "/app/note.txt",
                            "isDir": False,
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = await make_async_client(handler)
    try:
        fs = client.sprite("demo").filesystem("/app")
        path = fs / "note.txt"
        assert isinstance(path, AsyncSpritePath)
        assert isinstance(path.parent / path.name, AsyncSpritePath)

        await path.write_text("hello")
        assert await path.read_text() == "hello"
        assert await path.is_file()
        entries = [entry async for entry in fs.cwd.iterdir()]
        assert [entry.name for entry in entries] == ["note.txt"]
        assert all(isinstance(entry, AsyncSpritePath) for entry in entries)
    finally:
        await client.aclose()

    assert ("PUT", "/v1/sprites/demo/fs/write") in seen
    assert ("GET", "/v1/sprites/demo/fs/read") in seen


@pytest.mark.asyncio
async def test_async_sprite_checkpoint_service_and_policy_operations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/checkpoints") and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "cp-1",
                        "create_time": "2026-01-12T21:24:42Z",
                        "comment": "before",
                    }
                ],
            )
        if path.endswith("/checkpoint"):
            return httpx.Response(200, text='{"type":"complete","data":"cp-2"}\n')
        if path.endswith("/restore"):
            return httpx.Response(200, text='{"type":"complete"}\n')
        if path.endswith("/services") and request.method == "GET":
            return httpx.Response(200, json=[{"name": "web", "cmd": "serve"}])
        if path.endswith("/services/web") and request.method == "GET":
            return httpx.Response(200, json={"name": "web", "cmd": "serve"})
        if path.endswith("/services/web") and request.method == "PUT":
            assert json.loads(request.content) == {
                "cmd": "serve",
                "env": {"MODE": "test"},
            }
            return httpx.Response(200, text='{"type":"started"}\n')
        if path.endswith("/policy/network") and request.method == "GET":
            return httpx.Response(
                200, json={"rules": [{"domain": "example.com", "action": "allow"}]}
            )
        if path.endswith("/policy/network") and request.method == "POST":
            assert json.loads(request.content) == {
                "rules": [{"domain": "example.com", "action": "allow"}]
            }
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = await make_async_client(handler)
    sprite = client.sprite("demo")
    try:
        checkpoints = await sprite.list_checkpoints()
        assert checkpoints[0].id == "cp-1"

        checkpoint_events = list(await sprite.create_checkpoint("before"))
        restore_events = list(await sprite.restore_checkpoint("cp-1"))
        assert checkpoint_events[0].data == "cp-2"
        assert restore_events[0].type == "complete"

        services = await sprite.list_services()
        service = await sprite.get_service("web")
        service_events = list(
            await sprite.create_service("web", "serve", env={"MODE": "test"})
        )
        assert services[0].name == service.name == "web"
        assert service_events[0].type == "started"

        policy = await sprite.get_network_policy()
        assert policy.rules[0].domain == "example.com"
        await sprite.update_network_policy(
            NetworkPolicy(rules=[PolicyRule(domain="example.com", action="allow")])
        )
    finally:
        await client.aclose()
