"""Internal helpers for API parsing and URL construction."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

from .types import SpriteInfo, URLSettings


def quote_path_segment(value: str) -> str:
    """Quote a single URL path segment."""
    return quote(value, safe="")


def sprite_base_url(base_url: str, name: str) -> str:
    """Build the base REST URL for a sprite."""
    return f"{base_url.rstrip('/')}/v1/sprites/{quote_path_segment(name)}"


def websocket_base_url(base_url: str) -> str:
    """Convert an HTTP(S) base URL to a WS(S) base URL."""
    if base_url.startswith("https"):
        return "wss" + base_url[5:]
    if base_url.startswith("http"):
        return "ws" + base_url[4:]
    return base_url


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse API datetime strings, returning None for missing or invalid values."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_url_settings(data: Any) -> Optional[URLSettings]:
    """Parse URL settings from an API response."""
    if not isinstance(data, dict):
        return None
    return URLSettings(
        auth=data.get("auth"),
        private_access=data.get("private_access"),
    )


def parse_sprite_info(data: dict[str, Any]) -> SpriteInfo:
    """Parse sprite metadata from an API response."""
    return SpriteInfo(
        id=data.get("id", ""),
        name=data.get("name", ""),
        organization=data.get("organization") or data.get("org_slug", ""),
        status=data.get("status", ""),
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at")),
        bucket_name=data.get("bucket_name"),
        primary_region=data.get("primary_region"),
        url=data.get("url"),
        url_settings=parse_url_settings(data.get("url_settings")),
        version=data.get("version"),
        environment_version=data.get("environment_version"),
        labels=data.get("labels") or [],
        last_running_at=parse_datetime(data.get("last_running_at")),
        last_warming_at=parse_datetime(data.get("last_warming_at")),
    )
