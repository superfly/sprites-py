"""
Sprites client implementation
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import httpx

from .types import (
    ClientOptions,
    SpriteConfig,
    SpriteInfo,
    SpriteList,
    ListOptions,
    URLSettings,
)
from .exceptions import (
    SpriteError,
    NetworkError,
    AuthenticationError,
    NotFoundError,
)


class SpritesClient:
    """Main client for interacting with the Sprites API."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.sprites.dev",
        timeout: float = 30.0,
        control_mode: bool = False,
    ):
        """
        Initialize the Sprites client.

        Args:
            token: Authentication token
            base_url: Base URL for the API (default: https://api.sprites.dev)
            timeout: HTTP request timeout in seconds (default: 30.0)
            control_mode: Enable control mode for multiplexed WebSocket operations (default: False)
        """
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.control_mode = control_mode
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> "SpritesClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    @property
    def http_client(self) -> "_AuthenticatedClient":
        """Get an HTTP client with pre-configured authorization headers."""
        return _AuthenticatedClient(self._client, self.token)

    def _headers(self) -> Dict[str, str]:
        """Get default headers with authorization."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: httpx.Response, operation: str) -> None:
        """Handle HTTP response errors."""
        if response.status_code == 401:
            raise AuthenticationError(f"Authentication failed for {operation}")
        if response.status_code == 404:
            raise NotFoundError(f"Resource not found for {operation}")
        if not response.is_success:
            try:
                body = response.text
            except Exception:
                body = ""
            raise SpriteError(
                f"Failed {operation} (status {response.status_code}): {body}"
            )

    def _sprite_url(self, name: str) -> str:
        return f"{self.base_url}/v1/sprites/{quote(name, safe='')}"

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def _parse_url_settings(cls, data: Any) -> Optional[URLSettings]:
        if not isinstance(data, dict):
            return None
        return URLSettings(
            auth=data.get("auth"),
            private_access=data.get("private_access"),
        )

    @classmethod
    def _parse_sprite_info(cls, data: Dict[str, Any]) -> SpriteInfo:
        return SpriteInfo(
            id=data.get("id", ""),
            name=data.get("name", ""),
            organization=data.get("organization") or data.get("org_slug", ""),
            status=data.get("status", ""),
            created_at=cls._parse_datetime(data.get("created_at")),
            updated_at=cls._parse_datetime(data.get("updated_at")),
            bucket_name=data.get("bucket_name"),
            primary_region=data.get("primary_region"),
            url=data.get("url"),
            url_settings=cls._parse_url_settings(data.get("url_settings")),
            version=data.get("version"),
            environment_version=data.get("environment_version"),
            labels=data.get("labels") or [],
            last_running_at=cls._parse_datetime(data.get("last_running_at")),
            last_warming_at=cls._parse_datetime(data.get("last_warming_at")),
        )

    def sprite(self, name: str) -> "Sprite":
        """
        Get a handle to a sprite (doesn't create it on the server).

        Args:
            name: Sprite name

        Returns:
            Sprite instance
        """
        from .sprite import Sprite
        return Sprite(name, self)

    def create_sprite(
        self,
        name: str,
        config: Optional[SpriteConfig] = None,
        url_settings: Optional[URLSettings] = None,
        labels: Optional[List[str]] = None,
        wait_for_capacity: bool = False,
        runtime: Optional[str] = None,
    ) -> "Sprite":
        """
        Create a new sprite.

        Args:
            name: Sprite name
            config: Optional configuration
            url_settings: Optional URL access settings
            labels: Optional labels to attach to the sprite
            wait_for_capacity: Wait until capacity is available before returning
            runtime: Optional runtime variant ("default" or "dev")

        Returns:
            Created Sprite instance
        """
        from .sprite import Sprite

        request: Dict[str, Any] = {"name": name}
        if config:
            request["config"] = {
                k: v for k, v in {
                    "ram_mb": config.ram_mb,
                    "cpus": config.cpus,
                    "region": config.region,
                    "storage_gb": config.storage_gb,
                }.items() if v is not None
            }
        if url_settings:
            request["url_settings"] = {
                k: v for k, v in {
                    "auth": url_settings.auth,
                    "private_access": url_settings.private_access,
                }.items() if v is not None
            }
        if labels is not None:
            request["labels"] = labels
        if wait_for_capacity:
            request["wait_for_capacity"] = True
        if runtime is not None:
            request["runtime"] = runtime

        try:
            response = self._client.post(
                f"{self.base_url}/v1/sprites",
                headers=self._headers(),
                json=request,
                timeout=120.0,  # 2 minute timeout for creation
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error creating sprite: {e}")

        self._handle_response(response, "create sprite")
        result = response.json()
        sprite = Sprite(result["name"], self)
        sprite._update_from_info(result)
        return sprite

    def get_sprite(self, name: str) -> "Sprite":
        """
        Get information about a sprite.

        Args:
            name: Sprite name

        Returns:
            Sprite instance with populated info
        """
        from .sprite import Sprite

        try:
            response = self._client.get(
                self._sprite_url(name),
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error getting sprite: {e}")

        self._handle_response(response, f"get sprite '{name}'")
        info = response.json()
        sprite = Sprite(info["name"], self)
        sprite._update_from_info(info)
        return sprite

    def list_sprites(self, options: Optional[ListOptions] = None) -> SpriteList:
        """
        List sprites with optional filtering and pagination.

        Args:
            options: Optional filtering/pagination options

        Returns:
            Paginated list of sprites
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
            response = self._client.get(
                f"{self.base_url}/v1/sprites",
                headers=self._headers(),
                params=params,
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error listing sprites: {e}")

        self._handle_response(response, "list sprites")
        data = response.json()

        sprites = [self._parse_sprite_info(s) for s in data.get("sprites", [])]

        return SpriteList(
            sprites=sprites,
            has_more=data.get("has_more", False),
            next_continuation_token=data.get("next_continuation_token"),
            running=data.get("running", 0),
            warm=data.get("warm", 0),
            cold=data.get("cold", 0),
        )

    def list_all_sprites(self, prefix: Optional[str] = None) -> List["Sprite"]:
        """
        List all sprites, handling pagination automatically.

        Args:
            prefix: Optional name prefix filter

        Returns:
            List of all Sprite instances
        """
        from .sprite import Sprite

        all_sprites: List[Sprite] = []
        continuation_token: Optional[str] = None

        while True:
            result = self.list_sprites(ListOptions(
                prefix=prefix,
                max_results=100,
                continuation_token=continuation_token,
            ))

            for info in result.sprites:
                sprite = Sprite(info.name, self)
                all_sprites.append(sprite)

            if not result.has_more:
                break
            continuation_token = result.next_continuation_token

        return all_sprites

    def destroy_sprite(self, name: str) -> None:
        """
        Destroy a sprite.

        Args:
            name: Sprite name
        """
        try:
            response = self._client.delete(
                self._sprite_url(name),
                headers=self._headers(),
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error deleting sprite: {e}")

        if response.status_code != 204:
            self._handle_response(response, f"destroy sprite '{name}'")

    def delete_sprite(self, name: str) -> None:
        """
        Delete a sprite.

        This is an alias for destroy_sprite(), named after the HTTP DELETE method.

        Args:
            name: Sprite name
        """
        self.destroy_sprite(name)

    def upgrade_sprite(self, name: str) -> None:
        """
        Upgrade a sprite to the latest version.

        Args:
            name: Sprite name
        """
        try:
            response = self._client.post(
                f"{self._sprite_url(name)}/upgrade",
                headers=self._headers(),
                timeout=60.0,
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error upgrading sprite: {e}")

        if response.status_code not in (200, 204):
            self._handle_response(response, f"upgrade sprite '{name}'")

    def update_url_settings(self, name: str, settings: URLSettings) -> None:
        """
        Update URL authentication settings for a sprite.

        Args:
            name: Sprite name
            settings: URL settings with auth: "public" for no auth, "sprite" for authenticated
        """
        try:
            response = self._client.put(
                self._sprite_url(name),
                headers=self._headers(),
                json={
                    "url_settings": {
                        k: v for k, v in {
                            "auth": settings.auth,
                            "private_access": settings.private_access,
                        }.items() if v is not None
                    }
                },
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error updating URL settings: {e}")

        self._handle_response(response, f"update URL settings for '{name}'")

    def update_sprite(
        self,
        name: str,
        *,
        url_settings: Optional[URLSettings] = None,
        labels: Optional[List[str]] = None,
    ) -> "Sprite":
        """
        Update mutable sprite settings.

        Args:
            name: Sprite name
            url_settings: Optional URL access settings
            labels: Optional replacement labels

        Returns:
            Updated Sprite instance.
        """
        if url_settings is None and labels is None:
            raise ValueError("url_settings or labels is required")

        body: Dict[str, Any] = {}
        if url_settings is not None:
            body["url_settings"] = {
                k: v for k, v in {
                    "auth": url_settings.auth,
                    "private_access": url_settings.private_access,
                }.items() if v is not None
            }
        if labels is not None:
            body["labels"] = labels

        try:
            response = self._client.put(
                self._sprite_url(name),
                headers=self._headers(),
                json=body,
            )
        except httpx.RequestError as e:
            raise NetworkError(f"Network error updating sprite: {e}")

        self._handle_response(response, f"update sprite '{name}'")
        info = response.json()
        sprite = self.sprite(info.get("name", name))
        sprite._update_from_info(info)
        return sprite

    @staticmethod
    def create_token(
        fly_macaroon: str,
        org_slug: str,
        invite_code: Optional[str] = None
    ) -> str:
        """
        Create a sprite access token using a Fly.io macaroon token.

        Args:
            fly_macaroon: Fly.io macaroon token
            org_slug: Organization slug
            invite_code: Optional invite code

        Returns:
            Access token string
        """
        api_url = "https://api.sprites.dev"
        url = f"{api_url}/v1/organizations/{org_slug}/tokens"

        body: Dict[str, Any] = {"description": "Sprite SDK Token"}
        if invite_code:
            body["invite_code"] = invite_code

        with httpx.Client(timeout=30.0) as client:
            try:
                response = client.post(
                    url,
                    headers={
                        "Authorization": f"FlyV1 {fly_macaroon}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            except httpx.RequestError as e:
                raise NetworkError(f"Network error creating token: {e}")

            if not response.is_success:
                raise SpriteError(
                    f"API returned status {response.status_code}: {response.text}"
                )

            result = response.json()
            if "token" not in result:
                raise SpriteError("No token returned in response")

            return result["token"]


class _AuthenticatedClient:
    """Wrapper around httpx.Client that adds authorization headers to all requests."""

    def __init__(self, client: httpx.Client, token: str):
        self._client = client
        self._token = token

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())
        return self._client.get(url, headers=headers, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())
        return self._client.post(url, headers=headers, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())
        return self._client.put(url, headers=headers, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.update(self._auth_headers())
        return self._client.delete(url, headers=headers, **kwargs)
