"""Network policy operations for Sprites."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

from sprites.exceptions import APIError
from sprites.types import NetworkPolicy, PolicyRule

if TYPE_CHECKING:
    from sprites.sprite import Sprite


def _sprite_base_url(sprite: Sprite) -> str:
    return f"{sprite.client.base_url}/v1/sprites/{quote(sprite.name, safe='')}"


def get_network_policy(sprite: Sprite) -> NetworkPolicy:
    """Get the current network policy for a sprite.

    Args:
        sprite: The sprite to get the policy for.

    Returns:
        The network policy.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_base_url(sprite)}/policy/network"

    try:
        response = sprite.client.http_client.get(url)
    except httpx.RequestError as e:
        raise APIError(f"Failed to get network policy: {e}") from e

    if response.status_code != 200:
        raise APIError(
            f"Failed to get network policy (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )

    data = response.json()
    rules = []
    for rule_data in data.get("rules", []):
        rule = PolicyRule(
            domain=rule_data.get("domain"),
            action=rule_data.get("action"),
            include=rule_data.get("include"),
        )
        rules.append(rule)

    return NetworkPolicy(rules=rules)


def update_network_policy(sprite: Sprite, policy: NetworkPolicy) -> None:
    """Update the network policy for a sprite.

    Args:
        sprite: The sprite to update.
        policy: The new network policy.

    Raises:
        APIError: If the API call fails.
    """
    url = f"{_sprite_base_url(sprite)}/policy/network"

    # Convert policy to dict
    payload: dict[str, Any] = {
        "rules": [
            {
                k: v
                for k, v in {
                    "domain": rule.domain,
                    "action": rule.action,
                    "include": rule.include,
                }.items()
                if v is not None
            }
            for rule in policy.rules
        ]
    }

    try:
        response = sprite.client.http_client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    except httpx.RequestError as e:
        raise APIError(f"Failed to update network policy: {e}") from e

    if response.status_code == 400:
        raise APIError(
            f"Invalid policy: {response.text}",
            status_code=400,
            response=response.text,
        )

    if response.status_code != 204:
        raise APIError(
            f"Failed to update network policy (status {response.status_code})",
            status_code=response.status_code,
            response=response.text,
        )
