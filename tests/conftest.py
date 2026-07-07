"""Pytest configuration for Sprites SDK tests."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def make_mock_client():
    """Create SpritesClient instances backed by an httpx MockTransport."""
    import httpx

    from sprites import SpritesClient

    clients = []

    def factory(handler):
        client = SpritesClient("test-token", base_url="https://api.test")
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield factory

    for client in clients:
        client.close()


@pytest.fixture
def sprites_token() -> str:
    """Get the Sprites test token from environment."""
    token = os.environ.get("SPRITES_TEST_TOKEN")
    if not token:
        pytest.skip("SPRITES_TEST_TOKEN not set")
    return token


@pytest.fixture
def base_url() -> str:
    """Get the Sprites API base URL."""
    return os.environ.get("SPRITES_BASE_URL", "https://api.sprites.dev")
