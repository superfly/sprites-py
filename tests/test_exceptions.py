"""Tests for the Sprites SDK exceptions module."""

import json

from sprites.exceptions import (
    ERR_CODE_CONCURRENT_LIMIT_EXCEEDED,
    ERR_CODE_CREATION_RATE_LIMITED,
    APIError,
    parse_api_error,
)


class TestAPIError:
    """Tests for the APIError class."""

    def test_basic_error(self):
        """Test creating a basic APIError."""
        err = APIError("Something went wrong", status_code=500)
        assert str(err) == "Something went wrong"
        assert err.status_code == 500
        assert err.error_code is None

    def test_error_with_all_fields(self):
        """Test creating an APIError with all fields populated."""
        err = APIError(
            "Rate limit exceeded",
            status_code=429,
            response='{"error": "rate_limited"}',
            error_code="sprite_creation_rate_limited",
            limit=10,
            window_seconds=60,
            retry_after_seconds=30,
            current_count=5,
            upgrade_available=True,
            upgrade_url="https://fly.io/upgrade",
            retry_after_header=25,
            rate_limit_limit=100,
            rate_limit_remaining=0,
            rate_limit_reset=1706400000,
        )
        assert err.status_code == 429
        assert err.error_code == "sprite_creation_rate_limited"
        assert err.limit == 10
        assert err.window_seconds == 60
        assert err.retry_after_seconds == 30
        assert err.current_count == 5
        assert err.upgrade_available is True
        assert err.upgrade_url == "https://fly.io/upgrade"
        assert err.retry_after_header == 25
        assert err.rate_limit_limit == 100
        assert err.rate_limit_remaining == 0
        assert err.rate_limit_reset == 1706400000

    def test_is_rate_limit_error(self):
        """Test is_rate_limit_error method."""
        err_429 = APIError("Rate limited", status_code=429)
        err_500 = APIError("Server error", status_code=500)
        err_none = APIError("Unknown error")

        assert err_429.is_rate_limit_error() is True
        assert err_500.is_rate_limit_error() is False
        assert err_none.is_rate_limit_error() is False

    def test_is_creation_rate_limited(self):
        """Test is_creation_rate_limited method."""
        err_creation = APIError(
            "Rate limited",
            status_code=429,
            error_code=ERR_CODE_CREATION_RATE_LIMITED,
        )
        err_concurrent = APIError(
            "Limit exceeded",
            status_code=429,
            error_code=ERR_CODE_CONCURRENT_LIMIT_EXCEEDED,
        )
        err_other = APIError("Other error", status_code=429, error_code="other_error")

        assert err_creation.is_creation_rate_limited() is True
        assert err_concurrent.is_creation_rate_limited() is False
        assert err_other.is_creation_rate_limited() is False

    def test_is_concurrent_limit_exceeded(self):
        """Test is_concurrent_limit_exceeded method."""
        err_concurrent = APIError(
            "Limit exceeded",
            status_code=429,
            error_code=ERR_CODE_CONCURRENT_LIMIT_EXCEEDED,
        )
        err_creation = APIError(
            "Rate limited",
            status_code=429,
            error_code=ERR_CODE_CREATION_RATE_LIMITED,
        )

        assert err_concurrent.is_concurrent_limit_exceeded() is True
        assert err_creation.is_concurrent_limit_exceeded() is False

    def test_get_retry_after_seconds_prefers_json(self):
        """Test that get_retry_after_seconds prefers JSON field over header."""
        err = APIError(
            "Rate limited",
            status_code=429,
            retry_after_seconds=30,
            retry_after_header=60,
        )
        assert err.get_retry_after_seconds() == 30

    def test_get_retry_after_seconds_falls_back_to_header(self):
        """Test that get_retry_after_seconds falls back to header when JSON is not set."""
        err = APIError(
            "Rate limited",
            status_code=429,
            retry_after_header=60,
        )
        assert err.get_retry_after_seconds() == 60

    def test_get_retry_after_seconds_returns_none(self):
        """Test that get_retry_after_seconds returns None when neither is set."""
        err = APIError("Rate limited", status_code=429)
        assert err.get_retry_after_seconds() is None


class TestParseAPIError:
    """Tests for the parse_api_error function."""

    def test_returns_none_for_success_status(self):
        """Test that parse_api_error returns None for status < 400."""
        assert parse_api_error(200, b"OK") is None
        assert parse_api_error(201, b"Created") is None
        assert parse_api_error(204, b"") is None
        assert parse_api_error(301, b"Moved") is None
        assert parse_api_error(399, b"Something") is None

    def test_parses_json_body(self):
        """Test parsing a JSON error response body."""
        body = json.dumps(
            {
                "error": "sprite_creation_rate_limited",
                "message": "Rate limit exceeded",
                "limit": 10,
                "window_seconds": 60,
                "retry_after_seconds": 30,
                "upgrade_available": True,
                "upgrade_url": "https://fly.io/upgrade",
            }
        ).encode()

        err = parse_api_error(429, body)
        assert err is not None
        assert err.status_code == 429
        assert err.error_code == "sprite_creation_rate_limited"
        assert str(err) == "Rate limit exceeded"
        assert err.limit == 10
        assert err.window_seconds == 60
        assert err.retry_after_seconds == 30
        assert err.upgrade_available is True
        assert err.upgrade_url == "https://fly.io/upgrade"

    def test_parses_rate_limit_headers(self):
        """Test parsing rate limit headers."""
        headers = {
            "Retry-After": "30",
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1706400000",
        }
        body = b'{"error": "rate_limited", "message": "Too many requests"}'

        err = parse_api_error(429, body, headers)
        assert err is not None
        assert err.retry_after_header == 30
        assert err.rate_limit_limit == 100
        assert err.rate_limit_remaining == 0
        assert err.rate_limit_reset == 1706400000

    def test_parses_lowercase_headers(self):
        """Test parsing lowercase headers (as some HTTP libraries normalize them)."""
        headers = {
            "retry-after": "30",
            "x-ratelimit-limit": "100",
        }
        body = b'{"message": "Rate limited"}'

        err = parse_api_error(429, body, headers)
        assert err is not None
        assert err.retry_after_header == 30
        assert err.rate_limit_limit == 100

    def test_handles_non_json_body(self):
        """Test that non-JSON bodies are used as the message."""
        body = b"Internal Server Error: something went wrong"

        err = parse_api_error(500, body)
        assert err is not None
        assert err.status_code == 500
        assert str(err) == "Internal Server Error: something went wrong"
        assert err.error_code is None

    def test_handles_empty_body(self):
        """Test handling empty response body."""
        err = parse_api_error(500, b"")
        assert err is not None
        assert err.status_code == 500
        assert "API error (status 500)" in str(err)

    def test_handles_invalid_header_values(self):
        """Test that invalid header values don't cause errors."""
        headers = {
            "Retry-After": "not-a-number",
            "X-RateLimit-Limit": "invalid",
        }
        body = b'{"message": "Error"}'

        err = parse_api_error(429, body, headers)
        assert err is not None
        assert err.retry_after_header is None
        assert err.rate_limit_limit is None

    def test_concurrent_limit_error(self):
        """Test parsing a concurrent limit error response."""
        body = json.dumps(
            {
                "error": "concurrent_sprite_limit_exceeded",
                "message": "Too many concurrent sprites",
                "current_count": 5,
                "limit": 5,
            }
        ).encode()

        err = parse_api_error(429, body)
        assert err is not None
        assert err.error_code == ERR_CODE_CONCURRENT_LIMIT_EXCEEDED
        assert err.current_count == 5
        assert err.limit == 5
        assert err.is_concurrent_limit_exceeded() is True
