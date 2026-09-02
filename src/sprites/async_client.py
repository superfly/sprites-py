"""Asynchronous Sprites API client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import httpx

from ._signals import signal_headers
from ._utils import parse_sprite_info, sprite_base_url
from .client import _handle_response
from .exceptions import NetworkError, SpriteError
from .types import ListOptions, SpriteConfig, SpriteList, URLSettings

if TYPE_CHECKING:
    from .async_sprite import AsyncSprite


class AsyncSpritesClient:
    """Async client for the Sprites API.

    This client owns an :class:`httpx.AsyncClient`; it does not call the sync
    client or submit work to a thread pool.
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.sprites.dev",
        timeout: float = 30.0,
        control_mode: bool = False,
    ):
        """Initialize an async client.

        Args:
            token: Sprites API access token.
            base_url: Base URL for the Sprites API.
            timeout: Default HTTP request timeout in seconds.
            control_mode: Enable multiplexed command WebSocket connections.
        """
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.control_mode = control_mode
        self._client = httpx.AsyncClient(timeout=timeout, headers=signal_headers())

    async def __aenter__(self) -> "AsyncSpritesClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close this client's control pools and underlying HTTP client."""
        from .control import close_control_pools

        try:
            await close_control_pools(self)
        finally:
            await self._client.aclose()

    @property
    def http_client(self) -> "_AsyncAuthenticatedClient":
        """Return an async HTTP client that adds this client's token."""
        return _AsyncAuthenticatedClient(self._client, self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response, operation: str) -> None:
        """Handle HTTP response errors consistently with the sync client."""
        _handle_response(response, operation)

    def _sprite_url(self, name: str) -> str:
        return sprite_base_url(self.base_url, name)

    def sprite(self, name: str) -> "AsyncSprite":
        """Return an unfetched async sprite handle.

        Args:
            name: Sprite name.

        Returns:
            An async handle that performs no request until an I/O method is used.
        """
        from .async_sprite import AsyncSprite

        return AsyncSprite(name, self)

    async def create_sprite(
        self,
        name: str,
        config: Optional[SpriteConfig] = None,
        url_settings: Optional[URLSettings] = None,
        labels: Optional[List[str]] = None,
        wait_for_capacity: bool = False,
        runtime: Optional[str] = None,
    ) -> "AsyncSprite":
        """Create a sprite and return its populated async handle.

        Args:
            name: Sprite name.
            config: Optional machine configuration.
            url_settings: Optional URL access settings.
            labels: Labels to attach to the sprite.
            wait_for_capacity: Wait for capacity instead of returning immediately.
            runtime: Optional runtime variant.

        Returns:
            The newly created sprite.

        Raises:
            AuthenticationError: If the API token is rejected.
            NetworkError: If the API request fails at the transport layer.
            SpriteError: If the API returns another unsuccessful response.
        """
        request: Dict[str, Any] = {"name": name}
        if config:
            request["config"] = {
                k: v
                for k, v in {
                    "ram_mb": config.ram_mb,
                    "cpus": config.cpus,
                    "region": config.region,
                    "storage_gb": config.storage_gb,
                }.items()
                if v is not None
            }
        if url_settings:
            request["url_settings"] = {
                k: v
                for k, v in {
                    "auth": url_settings.auth,
                    "private_access": url_settings.private_access,
                }.items()
                if v is not None
            }
        if labels is not None:
            request["labels"] = labels
        if wait_for_capacity:
            request["wait_for_capacity"] = True
        if runtime is not None:
            request["runtime"] = runtime

        try:
            response = await self._client.post(
                f"{self.base_url}/v1/sprites",
                headers=self._headers(),
                json=request,
                timeout=120.0,
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error creating sprite: {exc}") from exc

        self._handle_response(response, "create sprite")
        result = response.json()
        sprite = self.sprite(result["name"])
        sprite._update_from_info(result)
        return sprite

    async def get_sprite(self, name: str) -> "AsyncSprite":
        """Fetch a sprite and return its populated async handle.

        Args:
            name: Sprite name.

        Returns:
            A sprite populated with the latest server metadata.

        Raises:
            NotFoundError: If the sprite does not exist.
            NetworkError: If the API request fails at the transport layer.
        """
        try:
            response = await self._client.get(
                self._sprite_url(name), headers=self._headers()
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error getting sprite: {exc}") from exc

        self._handle_response(response, f"get sprite '{name}'")
        info = response.json()
        sprite = self.sprite(info["name"])
        sprite._update_from_info(info)
        return sprite

    async def list_sprites(self, options: Optional[ListOptions] = None) -> SpriteList:
        """List one page of sprites.

        Args:
            options: Optional filtering and pagination settings.

        Returns:
            A page of sprite metadata and continuation information.
        """
        params: Dict[str, Any] = {}
        if options:
            if options.max_results:
                params["max_results"] = options.max_results
            if options.continuation_token:
                params["continuation_token"] = options.continuation_token
            if options.prefix:
                params["prefix"] = options.prefix
            if options.bulk_load:
                params["bulk_load"] = "true"

        try:
            response = await self._client.get(
                f"{self.base_url}/v1/sprites",
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error listing sprites: {exc}") from exc

        self._handle_response(response, "list sprites")
        data = response.json()
        return SpriteList(
            sprites=[parse_sprite_info(item) for item in data.get("sprites", [])],
            has_more=data.get("has_more", False),
            next_continuation_token=data.get("next_continuation_token"),
            running=data.get("running", 0),
            warm=data.get("warm", 0),
            cold=data.get("cold", 0),
        )

    async def list_all_sprites(
        self, prefix: Optional[str] = None
    ) -> List["AsyncSprite"]:
        """List all sprites, following continuation tokens.

        Args:
            prefix: Optional sprite-name prefix.

        Returns:
            Unfetched async handles for every matching sprite.
        """
        sprites: List["AsyncSprite"] = []
        continuation_token: Optional[str] = None
        while True:
            page = await self.list_sprites(
                ListOptions(
                    prefix=prefix,
                    max_results=100,
                    continuation_token=continuation_token,
                )
            )
            sprites.extend(self.sprite(info.name) for info in page.sprites)
            if not page.has_more:
                return sprites
            continuation_token = page.next_continuation_token

    async def destroy_sprite(self, name: str) -> None:
        """Destroy a sprite.

        Args:
            name: Sprite name.
        """
        try:
            response = await self._client.delete(
                self._sprite_url(name), headers=self._headers()
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error deleting sprite: {exc}") from exc
        if response.status_code != 204:
            self._handle_response(response, f"destroy sprite '{name}'")

    async def delete_sprite(self, name: str) -> None:
        """Alias for :meth:`destroy_sprite`."""
        await self.destroy_sprite(name)

    async def upgrade_sprite(self, name: str) -> None:
        """Upgrade a sprite to the latest version."""
        try:
            response = await self._client.post(
                f"{self._sprite_url(name)}/upgrade",
                headers=self._headers(),
                timeout=60.0,
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error upgrading sprite: {exc}") from exc
        if response.status_code not in (200, 204):
            self._handle_response(response, f"upgrade sprite '{name}'")

    async def update_url_settings(self, name: str, settings: URLSettings) -> None:
        """Update only a sprite's URL settings.

        Args:
            name: Sprite name.
            settings: Replacement URL access settings.
        """
        await self._update_sprite_request(
            name,
            {
                "url_settings": {
                    k: v
                    for k, v in {
                        "auth": settings.auth,
                        "private_access": settings.private_access,
                    }.items()
                    if v is not None
                }
            },
            f"update URL settings for '{name}'",
        )

    async def update_sprite(
        self,
        name: str,
        *,
        url_settings: Optional[URLSettings] = None,
        labels: Optional[List[str]] = None,
    ) -> "AsyncSprite":
        """Partially update mutable sprite settings.

        Args:
            name: Sprite name.
            url_settings: Replacement URL access settings, when supplied.
            labels: Replacement labels, when supplied.

        Returns:
            A populated handle containing the updated metadata.

        Raises:
            ValueError: If no mutable field is supplied.
        """
        if url_settings is None and labels is None:
            raise ValueError("url_settings or labels is required")

        body: Dict[str, Any] = {}
        if url_settings is not None:
            body["url_settings"] = {
                k: v
                for k, v in {
                    "auth": url_settings.auth,
                    "private_access": url_settings.private_access,
                }.items()
                if v is not None
            }
        if labels is not None:
            body["labels"] = labels

        response = await self._update_sprite_request(
            name, body, f"update sprite '{name}'"
        )
        info = response.json()
        sprite = self.sprite(info.get("name", name))
        sprite._update_from_info(info)
        return sprite

    async def _update_sprite_request(
        self, name: str, body: Dict[str, Any], operation: str
    ) -> httpx.Response:
        try:
            response = await self._client.put(
                self._sprite_url(name), headers=self._headers(), json=body
            )
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error updating sprite: {exc}") from exc
        self._handle_response(response, operation)
        return response

    @staticmethod
    async def create_token(
        fly_macaroon: str, org_slug: str, invite_code: Optional[str] = None
    ) -> str:
        """Create a sprite access token without blocking the event loop.

        Args:
            fly_macaroon: Fly.io macaroon token.
            org_slug: Fly.io organization slug.
            invite_code: Optional Sprites invite code.

        Returns:
            The newly minted Sprites API token.

        Raises:
            NetworkError: If the token request fails at the transport layer.
            SpriteError: If the API rejects the request or omits the token.
        """
        body: Dict[str, Any] = {"description": "Sprite SDK Token"}
        if invite_code:
            body["invite_code"] = invite_code

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"https://api.sprites.dev/v1/organizations/{org_slug}/tokens",
                    headers={
                        "Authorization": f"FlyV1 {fly_macaroon}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            except httpx.RequestError as exc:
                raise NetworkError(f"Network error creating token: {exc}") from exc
        if not response.is_success:
            raise SpriteError(
                f"API returned status {response.status_code}: {response.text}"
            )
        result = response.json()
        if "token" not in result:
            raise SpriteError("No token returned in response")
        token = result["token"]
        if not isinstance(token, str):
            raise SpriteError("Invalid token returned in response")
        return token


class _AsyncAuthenticatedClient:
    """Add bearer authentication to an ``httpx.AsyncClient``."""

    def __init__(self, client: httpx.AsyncClient, token: str):
        self._client = client
        self._token = token

    def _kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        headers = kwargs.pop("headers", {}).copy()
        headers["Authorization"] = f"Bearer {self._token}"
        kwargs["headers"] = headers
        return kwargs

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(url, **self._kwargs(kwargs))

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.post(url, **self._kwargs(kwargs))

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.put(url, **self._kwargs(kwargs))

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._client.delete(url, **self._kwargs(kwargs))
