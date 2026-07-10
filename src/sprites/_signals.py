"""Client-signals integration.

Attaches coarse, privacy-safe human-vs-AI-agent signals to outbound Sprites API
requests using github.com/superfly/client-signals: a set of ``Fly-Client-*``
headers plus a User-Agent suffix, so backend traffic can be attributed to
humans vs. agents.

Detection is computed once per process (never per request). Attribution is
best-effort and never changes request behavior.

Opting out: set ``SPRITES_CLIENT_SIGNALS`` to ``0`` / ``off`` / ``false`` /
``no``. When disabled (or if the ``client_signals`` package is unavailable),
requests still go out carrying only a plain ``sprites-py`` User-Agent (client
identification, not attribution) and no ``Fly-Client-*`` headers.
"""

from __future__ import annotations

import functools
import os
from typing import Dict

try:
    import client_signals
except ImportError:  # degrade gracefully; the dependency is declared but optional at runtime
    client_signals = None  # type: ignore[assignment]


def _base_user_agent() -> str:
    # Deferred import: avoids a circular import at module load time, since the
    # package __init__ imports the client which imports this module.
    from . import __version__

    return f"sprites-py/{__version__}"


_DISABLE_VALUES = {"0", "off", "false", "no", "disabled"}


def _disabled() -> bool:
    return os.environ.get("SPRITES_CLIENT_SIGNALS", "").strip().lower() in _DISABLE_VALUES


@functools.lru_cache(maxsize=1)
def _computed() -> Dict[str, str]:
    ua = _base_user_agent()
    # When opted out (or without the dependency) we never touch client_signals:
    # no detection runs and only the plain client-identification UA is sent.
    if client_signals is None or _disabled():
        return {"User-Agent": ua}
    signals = client_signals.detect_once()
    headers = client_signals.headers_for(signals)
    headers["User-Agent"] = f"{ua} {client_signals.user_agent_suffix(signals)}"
    return headers


def signal_headers() -> Dict[str, str]:
    """Return the client-signal headers (including User-Agent), computed once.

    Returns a fresh copy each call, so callers may safely merge in their own
    headers (e.g. Authorization) without mutating the cached result.
    """
    return dict(_computed())
