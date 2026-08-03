"""
Exceptions for the Sprites SDK
"""

import json
from typing import Any, Optional


class SpriteError(Exception):
    """Base exception for all Sprite SDK errors."""

    pass


class NetworkError(SpriteError):
    """Error during network communication."""

    pass


class AuthenticationError(SpriteError):
    """Authentication failed."""

    pass


class NotFoundError(SpriteError):
    """Resource not found."""

    pass


# Error codes returned by the API for rate limiting
ERR_CODE_CREATION_RATE_LIMITED = "sprite_creation_rate_limited"
ERR_CODE_CONCURRENT_LIMIT_EXCEEDED = "concurrent_sprite_limit_exceeded"


class APIError(SpriteError):
    """Structured error response from the Sprites API.

    Provides detailed information about rate limits and other API errors.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[str] = None,
        *,
        error_code: Optional[str] = None,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        retry_after_seconds: Optional[int] = None,
        current_count: Optional[int] = None,
        upgrade_available: bool = False,
        upgrade_url: Optional[str] = None,
        retry_after_header: Optional[int] = None,
        rate_limit_limit: Optional[int] = None,
        rate_limit_remaining: Optional[int] = None,
        rate_limit_reset: Optional[int] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response
        # Structured fields from JSON body
        self.error_code = error_code
        self.limit = limit
        self.window_seconds = window_seconds
        self.retry_after_seconds = retry_after_seconds
        self.current_count = current_count
        self.upgrade_available = upgrade_available
        self.upgrade_url = upgrade_url
        # Fields from HTTP headers
        self.retry_after_header = retry_after_header
        self.rate_limit_limit = rate_limit_limit
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset

    def is_rate_limit_error(self) -> bool:
        """Returns True if this is a 429 rate limit error."""
        return self.status_code == 429

    def is_creation_rate_limited(self) -> bool:
        """Returns True if this is a sprite creation rate limit error."""
        return self.error_code == ERR_CODE_CREATION_RATE_LIMITED

    def is_concurrent_limit_exceeded(self) -> bool:
        """Returns True if this is a concurrent sprite limit error."""
        return self.error_code == ERR_CODE_CONCURRENT_LIMIT_EXCEEDED

    def get_retry_after_seconds(self) -> Optional[int]:
        """Returns the number of seconds to wait before retrying.

        Prefers the JSON field, falling back to the header value.
        """
        if self.retry_after_seconds is not None and self.retry_after_seconds > 0:
            return self.retry_after_seconds
        return self.retry_after_header


def parse_api_error(
    status_code: int,
    body: bytes,
    headers: Optional[dict[str, str]] = None,
) -> Optional[APIError]:
    """Parse a structured API error from an HTTP response.

    Args:
        status_code: The HTTP status code.
        body: The response body as bytes.
        headers: Optional HTTP headers dict.

    Returns:
        An APIError if status_code >= 400, None otherwise.
    """
    if status_code < 400:
        return None

    headers = headers or {}

    # Parse rate limit headers
    retry_after_header: Optional[int] = None
    rate_limit_limit: Optional[int] = None
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset: Optional[int] = None

    if ra := headers.get("retry-after") or headers.get("Retry-After"):
        try:
            retry_after_header = int(ra)
        except ValueError:
            pass

    if rl := headers.get("x-ratelimit-limit") or headers.get("X-RateLimit-Limit"):
        try:
            rate_limit_limit = int(rl)
        except ValueError:
            pass

    if rr := headers.get("x-ratelimit-remaining") or headers.get(
        "X-RateLimit-Remaining"
    ):
        try:
            rate_limit_remaining = int(rr)
        except ValueError:
            pass

    if rs := headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset"):
        try:
            rate_limit_reset = int(rs)
        except ValueError:
            pass

    # Try to parse JSON body
    message = ""
    error_code: Optional[str] = None
    limit: Optional[int] = None
    window_seconds: Optional[int] = None
    retry_after_seconds: Optional[int] = None
    current_count: Optional[int] = None
    upgrade_available = False
    upgrade_url: Optional[str] = None

    body_str = body.decode("utf-8", errors="replace") if body else ""

    if body:
        try:
            data: dict[str, Any] = json.loads(body)
            error_code = data.get("error")
            message = data.get("message", "")
            limit = data.get("limit")
            window_seconds = data.get("window_seconds")
            retry_after_seconds = data.get("retry_after_seconds")
            current_count = data.get("current_count")
            upgrade_available = data.get("upgrade_available", False)
            upgrade_url = data.get("upgrade_url")
        except json.JSONDecodeError:
            # Use raw body as message
            message = body_str

    # Fallback message if nothing was parsed
    if not message and not error_code:
        message = f"API error (status {status_code})"

    return APIError(
        message=message or error_code or f"API error (status {status_code})",
        status_code=status_code,
        response=body_str,
        error_code=error_code,
        limit=limit,
        window_seconds=window_seconds,
        retry_after_seconds=retry_after_seconds,
        current_count=current_count,
        upgrade_available=upgrade_available,
        upgrade_url=upgrade_url,
        retry_after_header=retry_after_header,
        rate_limit_limit=rate_limit_limit,
        rate_limit_remaining=rate_limit_remaining,
        rate_limit_reset=rate_limit_reset,
    )


class ExecError(SpriteError):
    """Command execution failed with non-zero exit code."""

    def __init__(
        self, message: str, exit_code: int, stdout: bytes = b"", stderr: bytes = b""
    ):
        super().__init__(message)
        self._exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def exit_code(self) -> int:
        """Return the exit code of the command."""
        return self._exit_code


# Alias for compatibility with Go SDK naming
ExitError = ExecError


class TimeoutError(SpriteError):
    """Command execution timed out."""

    pass


class FilesystemError(SpriteError):
    """Error during filesystem operation."""

    def __init__(
        self, message: str, operation: str, path: str, code: Optional[str] = None
    ):
        super().__init__(message)
        self.operation = operation
        self.path = path
        self.code = code

    def __str__(self) -> str:
        if self.code:
            return f"{self.operation} {self.path}: {self.args[0]} ({self.code})"
        return f"{self.operation} {self.path}: {self.args[0]}"


class FileNotFoundError_(FilesystemError):
    """File or directory not found."""

    def __init__(self, operation: str, path: str):
        super().__init__("file not found", operation, path, "ENOENT")


class IsADirectoryError_(FilesystemError):
    """Expected file but found directory."""

    def __init__(self, operation: str, path: str):
        super().__init__("is a directory", operation, path, "EISDIR")


class NotADirectoryError_(FilesystemError):
    """Expected directory but found file."""

    def __init__(self, operation: str, path: str):
        super().__init__("not a directory", operation, path, "ENOTDIR")


class PermissionError_(FilesystemError):
    """Permission denied."""

    def __init__(self, operation: str, path: str):
        super().__init__("permission denied", operation, path, "EACCES")


class FileExistsError_(FilesystemError):
    """File already exists."""

    def __init__(self, operation: str, path: str):
        super().__init__("file exists", operation, path, "EEXIST")


class DirectoryNotEmptyError(FilesystemError):
    """Directory is not empty."""

    def __init__(self, operation: str, path: str):
        super().__init__("directory not empty", operation, path, "ENOTEMPTY")
