"""Client-signals integration.

Attaches coarse, privacy-safe human-vs-AI-agent signals to outbound Sprites API
requests using github.com/superfly/client-signals: a set of ``Fly-Client-*``
headers plus a User-Agent suffix, so backend traffic can be attributed to
humans vs. agents.

Detection is computed once per process (never per request). Attribution is
best-effort and never changes request behavior: if the ``client_signals``
package is unavailable, requests still go out, carrying only a plain
``sprites-py`` User-Agent.
"""

from __future__ import annotations

import functools
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


@functools.lru_cache(maxsize=1)
def _computed() -> Dict[str, str]:
    ua = _base_user_agent()
    if client_signals is None:
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
