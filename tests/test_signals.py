"""Tests for client-signals integration (Fly-Client-* headers + User-Agent)."""

import types

import httpx
import pytest

import sprites._signals as signals_module
import sprites.checkpoint as checkpoint_mod
import sprites.client as client_module
import sprites.services as services_mod
import sprites.session as session_mod
from sprites import SpritesClient
from sprites._signals import signal_headers
from sprites.exceptions import APIError

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


@pytest.mark.parametrize(
    "value", ["0", "off", "false", "no", "disabled", "OFF", " No "]
)
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


# -- transient (non-shared) REST clients must also carry signals --------------
#
# Checkpoint, service, and session-kill paths each build their own httpx.Client
# instead of using SpritesClient._client, so they need signals merged in too.


class _CapturingClient:
    """Records the headers a transient client is constructed with, then fails
    the request (so we don't need a real server or response parsing)."""

    captured_headers = None

    def __init__(self, *args, **kwargs):
        type(self).captured_headers = kwargs.get("headers") or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _fail(self, *args, **kwargs):
        raise httpx.RequestError("no network in tests")

    get = post = put = delete = _fail


def _fake_sprite():
    client = types.SimpleNamespace(token="tok", base_url="https://api.sprites.dev")
    return types.SimpleNamespace(name="s", client=client)


_BYPASS_CALLS = [
    ("create_checkpoint", lambda s: checkpoint_mod.create_checkpoint(s, "c")),
    ("restore_checkpoint", lambda s: checkpoint_mod.restore_checkpoint(s, "v1")),
    ("create_service", lambda s: services_mod.create_service(s, "web", "run")),
    ("start_service", lambda s: services_mod.start_service(s, "web")),
    ("stop_service", lambda s: services_mod.stop_service(s, "web")),
    ("kill_session", lambda s: session_mod.kill_session(s, "sess-1")),
]


@pytest.mark.parametrize("name, call", _BYPASS_CALLS, ids=[c[0] for c in _BYPASS_CALLS])
def test_transient_clients_carry_signal_headers(monkeypatch, name, call):
    _CapturingClient.captured_headers = None
    monkeypatch.setattr(httpx, "Client", _CapturingClient)

    with pytest.raises(APIError):  # the capturing client fails the request
        call(_fake_sprite())

    headers = _CapturingClient.captured_headers
    assert _has_fly_headers(headers), f"{name} sent no Fly-Client-* headers"
    assert any("bearer" in str(v).lower() for v in headers.values()), (
        f"{name} dropped Authorization"
    )


def test_transient_client_respects_opt_out(monkeypatch):
    # The opt-out must reach the transient paths too, not just the shared client.
    monkeypatch.setenv("SPRITES_CLIENT_SIGNALS", "0")
    _CapturingClient.captured_headers = None
    monkeypatch.setattr(httpx, "Client", _CapturingClient)

    with pytest.raises(APIError):
        checkpoint_mod.create_checkpoint(_fake_sprite(), "c")

    headers = _CapturingClient.captured_headers
    assert not _has_fly_headers(headers)
    assert any("bearer" in str(v).lower() for v in headers.values())  # auth still sent
