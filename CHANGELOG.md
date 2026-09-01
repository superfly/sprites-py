# Changelog

## Unreleased

## 0.6.0

- Added configurable five-minute timeouts for checkpoint creation and restore
  operations.
- Fixed shutdown cleanup so it does not create a new event loop or thread.
- Migrated command WebSocket handling off deprecated `websockets` APIs and
  raised the minimum supported `websockets` version to 14.
- Moved the separately published OpenAI Agents sandbox integration to
  [superfly/sprites-openai-agents](https://github.com/superfly/sprites-openai-agents).

## 0.5.1

- Report command WebSocket closures without an exit status as `NetworkError`
  instead of treating transport failures as successful exits or `ExecError: 1`.

## 0.5.0

- Reduced command completion latency by closing exec WebSockets immediately after the command finishes.
- Updated `client-signals` to 0.4.4, including Grok agent detection.

## 0.4.0

- Added `env` and `dir` support when creating services and parsing service responses.

## 0.2.0

- Updated the SDK for the current Sprites API response and request shapes.
- Added `destroy`/`destroy_sprite` as the preferred sprite removal terminology while keeping `delete`/`delete_sprite` aliases.
- Added public methods for mutable sprite updates, services, filesystem operations, and subprocess-style `Sprite.run()`.
- `ServiceWithState` now exposes service fields directly, such as `service.name`; the older nested `service.service.name` shape is no longer used.
- `ServiceState.started_at` and `ServiceState.next_restart_at` are parsed as `datetime` values instead of raw strings.
- Added mocked API contract and public-method tests for the client, sprite, filesystem, services, checkpoints, and streams.
