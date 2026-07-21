# Changelog

## 0.4.0

- Added `env` and `dir` support when creating services and parsing service responses.

## 0.2.0

- Updated the SDK for the current Sprites API response and request shapes.
- Added `destroy`/`destroy_sprite` as the preferred sprite removal terminology while keeping `delete`/`delete_sprite` aliases.
- Added public methods for mutable sprite updates, services, filesystem operations, and subprocess-style `Sprite.run()`.
- `ServiceWithState` now exposes service fields directly, such as `service.name`; the older nested `service.service.name` shape is no longer used.
- `ServiceState.started_at` and `ServiceState.next_restart_at` are parsed as `datetime` values instead of raw strings.
- Added mocked API contract and public-method tests for the client, sprite, filesystem, services, checkpoints, and streams.
