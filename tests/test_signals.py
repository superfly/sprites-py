"""Tests for client-signals integration (Fly-Client-* headers + User-Agent)."""

import httpx

import sprites.client as client_module
from sprites import SpritesClient
from sprites._signals import signal_headers

_PARENT_BUCKETS = {"node", "python", "shell", "other"}


def test_signal_headers_shape():
    headers = signal_headers()
    # Always identifies sprites-py, regardless of environment.
    assert headers["User-Agent"].startswith("sprites-py/")
    # Coarse, finite-valued signals.
    assert headers["Fly-Client-Parent"] in _PARENT_BUCKETS
    assert headers["Fly-Client-Interactive"] in {"true", "false"}


def test_signal_headers_returns_fresh_copy():
    a = signal_headers()
    a["Authorization"] = "Bearer x"  # callers merge auth on top
    b = signal_headers()
    assert "Authorization" not in b


def test_rest_client_carries_signal_headers():
    client = SpritesClient(token="test-token")
    headers = client._client.headers  # httpx default headers, sent on every request
    assert headers["user-agent"].startswith("sprites-py/")
    assert headers["fly-client-parent"] in _PARENT_BUCKETS
    assert headers["fly-client-interactive"] in {"true", "false"}


def test_user_agent_contains_signal_suffix():
    # The client-signals suffix is appended to the base UA, e.g.
    # "sprites-py/0.2.0 (interactive=false; parent=python)".
    ua = signal_headers()["User-Agent"]
    assert "interactive=" in ua and ua.rstrip().endswith(")")


class _RecordingResponse:
    status_code = 200
    is_success = True
    text = ""

    def json(self):
        return {"token": "minted-token"}


class _RecordingClient:
    """Captures how create_token constructs its transient httpx client."""

    init_kwargs = None
    post_headers = None

    def __init__(self, *args, **kwargs):
        type(self).init_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        type(self).post_headers = headers
        return _RecordingResponse()


def test_token_minting_path_excludes_signals(monkeypatch):
    # The auth/token path must never carry client-signals headers.
    monkeypatch.setattr(client_module.httpx, "Client", _RecordingClient)

    token = SpritesClient.create_token("fly-macaroon", "my-org")
    assert token == "minted-token"

    # Its transient client is built without signal default headers ...
    assert "headers" not in (_RecordingClient.init_kwargs or {})
    # ... and the request itself carries only auth/content-type, no Fly-Client-*.
    sent = _RecordingClient.post_headers or {}
    assert not any(k.lower().startswith("fly-client-") for k in sent)
    assert "sprites-py/" not in sent.get("User-Agent", "")
