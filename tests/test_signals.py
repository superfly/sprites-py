"""Tests for client-signals integration (Fly-Client-* headers + User-Agent)."""

import httpx
import pytest

import sprites.client as client_module
import sprites._signals as signals_module
from sprites import SpritesClient
from sprites._signals import signal_headers

_PARENT_BUCKETS = {"node", "python", "shell", "other"}


@pytest.fixture(autouse=True)
def _fresh_signal_cache():
    # signal_headers() caches its result for the process; clear it around each
    # test so env/dependency changes take effect and tests stay order-independent.
    signals_module._computed.cache_clear()
    yield
    signals_module._computed.cache_clear()


def _has_fly_headers(headers):
    return any(str(k).lower().startswith("fly-client-") for k in headers)


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


# -- opting out: the SDK must work fully without attribution -------------------


def test_disabled_sends_only_plain_user_agent(monkeypatch):
    monkeypatch.setenv("SPRITES_CLIENT_SIGNALS", "0")
    headers = signal_headers()
    # Only a plain client-identification UA; no attribution.
    assert list(headers) == ["User-Agent"]
    assert headers["User-Agent"].startswith("sprites-py/")
    assert "interactive=" not in headers["User-Agent"]  # no signal suffix
    assert not _has_fly_headers(headers)


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "disabled", "OFF", " No "])
def test_disable_accepts_common_falsey_values(monkeypatch, value):
    monkeypatch.setenv("SPRITES_CLIENT_SIGNALS", value)
    assert list(signal_headers()) == ["User-Agent"]


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("SPRITES_CLIENT_SIGNALS", raising=False)
    assert _has_fly_headers(signal_headers())


def test_disabled_client_still_works_without_fly_headers(monkeypatch):
    monkeypatch.setenv("SPRITES_CLIENT_SIGNALS", "off")
    client = SpritesClient(token="test-token")  # SDK constructs normally
    headers = client._client.headers
    assert headers["user-agent"].startswith("sprites-py/")
    assert not _has_fly_headers(headers.keys())
    client.close()


def test_disabled_never_runs_detection(monkeypatch):
    # Opting out must bypass client_signals entirely, not just drop its output.
    monkeypatch.setenv("SPRITES_CLIENT_SIGNALS", "off")
    if signals_module.client_signals is not None:
        def _boom(*args, **kwargs):
            raise AssertionError("detection must not run when disabled")

        monkeypatch.setattr(signals_module.client_signals, "detect_once", _boom)
    assert list(signal_headers()) == ["User-Agent"]  # does not raise


def test_works_without_client_signals_installed(monkeypatch):
    # Simulate the dependency being absent: the SDK degrades to a plain UA.
    monkeypatch.setattr(signals_module, "client_signals", None)
    headers = signal_headers()
    assert list(headers) == ["User-Agent"]
    assert headers["User-Agent"].startswith("sprites-py/")

    client = SpritesClient(token="test-token")  # still fully functional
    assert not _has_fly_headers(client._client.headers.keys())
    client.close()
