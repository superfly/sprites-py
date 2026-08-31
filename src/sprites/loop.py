"""Persistent event loop for connection reuse in sync API."""

from __future__ import annotations

import asyncio
import atexit
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

# Module-level state for the persistent event loop
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run the event loop in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def get_loop() -> asyncio.AbstractEventLoop:
    """Get or create the persistent event loop.

    Returns:
        The persistent event loop running in a background thread.
    """
    global _loop, _thread

    with _lock:
        if _loop is None or not _loop.is_running():
            # Create a new event loop
            _loop = asyncio.new_event_loop()

            # Start it in a background daemon thread
            _thread = threading.Thread(target=_run_loop, args=(_loop,), daemon=True)
            _thread.start()

            # Register cleanup on exit
            atexit.register(_cleanup)

    return _loop


def get_existing_loop() -> asyncio.AbstractEventLoop | None:
    """Return the running persistent event loop without creating one.

    Returns:
        The persistent event loop if it exists and is running, otherwise None.
    """
    with _lock:
        if _loop is None or not _loop.is_running():
            return None
        return _loop


def run_sync(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """Run a coroutine synchronously using the persistent event loop.

    This allows connection reuse across multiple sync calls by running
    all coroutines in the same persistent event loop.

    Args:
        coro: The coroutine to run.
        timeout: Optional timeout in seconds.

    Returns:
        The result of the coroutine.

    Raises:
        TimeoutError: If the timeout is exceeded.
        Exception: Any exception raised by the coroutine.
    """
    loop = get_loop()

    # Submit the coroutine to the persistent loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        raise


async def _cancel_all_tasks(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel all pending tasks in the loop."""
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

    if tasks:
        # Wait for all tasks to be cancelled
        await asyncio.gather(*tasks, return_exceptions=True)


def stop_loop() -> None:
    """Stop the persistent event loop.

    This should be called when all async work is done and you want to
    cleanly shut down the background thread.
    """
    global _loop, _thread

    with _lock:
        if _loop is not None and _loop.is_running():
            # Cancel all pending tasks before stopping the loop
            # This prevents "Task was destroyed but it is pending" warnings
            try:
                future = asyncio.run_coroutine_threadsafe(
                    _cancel_all_tasks(_loop), _loop
                )
                future.result(timeout=5.0)
            except Exception:
                pass

            _loop.call_soon_threadsafe(_loop.stop)

            if _thread is not None:
                _thread.join(timeout=2.0)

        _loop = None
        _thread = None


def _cleanup() -> None:
    """Clean up the persistent event loop on exit."""
    stop_loop()
