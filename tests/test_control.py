"""Tests for the control connection module."""

import pytest

from sprites import SpritesClient
from sprites._utils import quote_path_segment, websocket_base_url
from sprites.control import OpConn, StreamID


class StubControlConnection:
    """Minimal parent connection for testing operation state."""


@pytest.mark.asyncio
async def test_op_conn_distinguishes_exit_from_connection_close() -> None:
    op = OpConn(StubControlConnection())  # type: ignore[arg-type]

    op.close()

    assert op.received_exit is False
    assert op.get_exit_code() == -1


@pytest.mark.asyncio
async def test_op_conn_records_received_exit() -> None:
    op = OpConn(StubControlConnection())  # type: ignore[arg-type]

    op.handle_data(bytes([StreamID.EXIT, 4]))

    assert op.received_exit is True
    assert op.get_exit_code() == 4


@pytest.mark.asyncio
async def test_op_conn_completion_status_counts_as_received_exit() -> None:
    op = OpConn(StubControlConnection())  # type: ignore[arg-type]

    op.complete(0)

    assert op.received_exit is True
    assert op.get_exit_code() == 0


class TestControlModeClientOptions:
    """Tests for control mode client options."""

    def test_control_mode_false_by_default(self):
        """Control mode should be disabled by default (opt-in)."""
        client = SpritesClient(token="test-token")
        assert client.control_mode is False

    def test_control_mode_enabled_explicitly(self):
        """Control mode should be enabled when explicitly specified."""
        client = SpritesClient(token="test-token", control_mode=True)
        assert client.control_mode is True

    def test_control_mode_disabled_explicitly(self):
        """Control mode should be disabled when explicitly set to False."""
        client = SpritesClient(token="test-token", control_mode=False)
        assert client.control_mode is False


class TestSpriteControlMode:
    """Tests for sprite control mode."""

    def test_reflects_client_control_mode_true(self):
        """Sprite should reflect client's control mode setting when True."""
        client = SpritesClient(token="test-token", control_mode=True)
        sprite = client.sprite("test-sprite")
        assert sprite.use_control_mode() is True

    def test_reflects_client_control_mode_false(self):
        """Sprite should reflect client's control mode setting when False."""
        client = SpritesClient(token="test-token", control_mode=False)
        sprite = client.sprite("test-sprite")
        assert sprite.use_control_mode() is False

    def test_reflects_client_control_mode_default(self):
        """Sprite should reflect default client control mode (False - disabled by default)."""
        client = SpritesClient(token="test-token")
        sprite = client.sprite("test-sprite")
        assert sprite.use_control_mode() is False


class TestControlURLBuilding:
    """Tests for control endpoint URL building."""

    def test_control_endpoint_url_http(self):
        """Control endpoint URL should be built correctly for HTTP."""
        client = SpritesClient(token="test-token", base_url="http://localhost:8080")
        sprite = client.sprite("my-sprite")

        expected_url = "ws://localhost:8080/v1/sprites/my-sprite/control"

        actual_url = (
            f"{websocket_base_url(sprite.client.base_url)}"
            f"/v1/sprites/{quote_path_segment(sprite.name)}/control"
        )

        assert actual_url == expected_url

    def test_control_endpoint_url_https(self):
        """Control endpoint URL should convert HTTPS to WSS."""
        client = SpritesClient(token="test-token", base_url="https://api.sprites.dev")
        sprite = client.sprite("my-sprite")

        actual_url = (
            f"{websocket_base_url(sprite.client.base_url)}"
            f"/v1/sprites/{quote_path_segment(sprite.name)}/control"
        )

        assert actual_url.startswith("wss://")
        assert "my-sprite" in actual_url
        assert "/control" in actual_url

    def test_control_endpoint_url_encodes_sprite_name(self):
        """Control endpoint URL should encode the sprite path segment."""
        client = SpritesClient(token="test-token", base_url="https://api.sprites.dev")
        sprite = client.sprite("my sprite/name")

        actual_url = (
            f"{websocket_base_url(sprite.client.base_url)}"
            f"/v1/sprites/{quote_path_segment(sprite.name)}/control"
        )

        assert (
            actual_url == "wss://api.sprites.dev/v1/sprites/my%20sprite%2Fname/control"
        )
